from flask import Blueprint, jsonify, request
from routes.store import session_store
from llm.generator import Generator
from agents.prompts import QUIZ_MCQ_PROMPT, QUIZ_SHORT_ANSWER_PROMPT
from agents.prompts import GRADING_PROMPT
from utils.json_helper import extract_json
from utils.json_safe import json_error, parse_json_request
from utils.validation import (
    validate_extracted_text,
    validate_quiz_count,
    validate_session_id,
)
from db import (
    record_quiz_score,
    update_learner_state,
    record_metacognitive_checkin,
)
from agents.path_optimizer import optimize_learning_path
from agents.misconception_detector import detect_misconception
from agents.concept_registry import (
    get_canonical_concept,
    get_canonical_concepts,
)
quiz_bp = Blueprint('quiz', __name__)

@quiz_bp.route('/quiz/<session_id>', methods=['GET'])
def get_quiz(session_id):
    valid, error = validate_session_id(session_id)
    if not valid:
        return json_error(error)
    if session_id not in session_store:
        return jsonify({"error": "not_found"}), 404
        
    quiz = session_store[session_id].get("quiz")
    if not quiz:
        return jsonify({"mcq": [], "short_answer": []})
    return jsonify(quiz)

@quiz_bp.route('/quiz/generate/<session_id>', methods=['POST'])
def generate_quiz(session_id):
    valid, error = validate_session_id(session_id)
    if not valid:
        return json_error(error)
    if session_id not in session_store:
        return jsonify({"error": "not_found"}), 404
        
    full_text = session_store[session_id].get("full_text", "")
    valid, error = validate_extracted_text(full_text, max_length=None)
    if not valid:
        return jsonify({"error": "no_text"}), 400
    full_text = full_text[:6000]
        
    data, parse_error = parse_json_request(request)
    if parse_error:
        return json_error(parse_error)
    difficulty = data.get('difficulty', 'medium')
    count, count_error = validate_quiz_count(data.get('count', 5))
    if count_error:
        return json_error(count_error)
    
    # We could adjust prompts based on difficulty and count, but for now we'll append to the prompt.
    custom_instruction = f" Ensure the difficulty is {difficulty}. Generate exactly {count} questions."
    
    generator = Generator(json_mode=True)
    try:
        def generate_json(prompt_template, text):
            try:
                prompt = prompt_template + custom_instruction
                res = generator.chain.invoke({"context": text, "question": prompt})
                from utils.json_helper import extract_json
                return extract_json(res)
            except Exception:
                pass
            return None

        mcq = generate_json(QUIZ_MCQ_PROMPT, full_text) or {"mcq": []}
        sa = generate_json(QUIZ_SHORT_ANSWER_PROMPT, full_text) or {"short_answer": []}
        
        for i, m in enumerate(mcq.get("mcq", [])):
            m["id"] = f"mcq_{i}"
            
        for i, s in enumerate(sa.get("short_answer", [])):
            s["id"] = f"sa_{i}"
            
        quiz = {"mcq": mcq.get("mcq", []), "short_answer": sa.get("short_answer", [])}
        session_data = session_store[session_id]
        session_data["quiz"] = quiz
        session_store[session_id] = session_data
        return jsonify(quiz)
    except Exception as e:
        return jsonify({"error": "generation_failed", "message": str(e)}), 500
    
@quiz_bp.route('/quiz/grade', methods=['POST'])
def grade_answer():
    data, parse_error = parse_json_request(request)

    if parse_error:
        return json_error(parse_error)
    confidence_rating = data.get("confidence_rating")

    question = data.get("question", "")
    user_answer = data.get("user_answer", "")
    sample_answer = data.get("sample_answer", "")

    concept = get_canonical_concept(
        data.get("concept", question)
    )

    session_id = data.get("session_id", "")

    canonical_concepts = get_canonical_concepts(
        concept
    )

    concept_id_map = {
        f"C{i + 1}": item
        for i, item in enumerate(canonical_concepts)
    }

    canonical_concepts_for_prompt = "\n".join(
        f"{concept_id}: {concept_name}"
        for concept_id, concept_name in concept_id_map.items()
    )

    if session_id:
        valid, error = validate_session_id(session_id)

        if not valid:
            return json_error(error)

    normalized_user = user_answer.strip().lower()
    normalized_sample = sample_answer.strip().lower()

    # 1. Deterministic check for exact answers
    if normalized_user and normalized_user == normalized_sample:
        grading = {
            "score": 10,
            "feedback": "Your answer matches the sample answer.",
            "correct_concepts": [concept],
            "missed_concepts": [],
            "study_tip": "Continue to the next question."
        }

        if session_id:
            record_quiz_score(
                session_id,
                grading["score"]
            )

            update_learner_state(
                session_id,
                grading.get("correct_concepts", []),
                grading.get("missed_concepts", []),
                grading["score"]
            )

            if confidence_rating is not None:
                record_metacognitive_checkin(
        session_id,
        concept,
        int(confidence_rating),
    )

            grading["learning_path"] = optimize_learning_path(
                session_id,current_concept=concept,
            )

        return jsonify(grading)

    # 2. AI grading for non-exact answers
    generator = Generator(json_mode=True)

    try:
        res = generator.chain.invoke({
            "context": (
                f"Question: {question}\n"
                f"Concept: {concept}\n"
                f"Sample Answer: {sample_answer}"
            ),
            "question": GRADING_PROMPT.format(
                question=question,
                sample_answer=sample_answer,
                user_answer=user_answer,
                canonical_concepts=canonical_concepts_for_prompt
            )
        })

        grading = extract_json(res)

        correct_ids = grading.get(
            "correct_concepts",
            []
        )

        missed_ids = grading.get(
            "missed_concepts",
            []
        )

        grading["correct_concepts"] = [
            concept_id_map[concept_id]
            for concept_id in correct_ids
            if concept_id in concept_id_map
        ]

        grading["missed_concepts"] = [
            concept_id_map[concept_id]
            for concept_id in missed_ids
            if concept_id in concept_id_map
        ]

        print(
            "RAW GRADING RESPONSE:",
            repr(res)
        )

        if grading:
            score = float(
                grading.get("score", 0) or 0
            )

            # Detect misconception for incorrect answers.
            # This does not require a session.
            if score < 7:
                grading["misconception"] = detect_misconception(
                    question=question,
                    student_answer=user_answer,
                    sample_answer=sample_answer,
                    concept=concept,
                )

            # Update persistent learner data only
            # when a valid session exists.
            if session_id:
                record_quiz_score(
                    session_id,
                    score
                )

                correct_concepts = list(
                    grading.get(
                        "correct_concepts",
                        []
                    )
                )

                missed_concepts = list(
                    grading.get(
                        "missed_concepts",
                        []
                    )
                )

                if (
                    concept not in correct_concepts
                    and concept not in missed_concepts
                ):
                    if score >= 7:
                        correct_concepts.append(
                            concept
                        )
                    else:
                        missed_concepts.append(
                            concept
                        )

                misconception_severity = None

                if grading.get("misconception"):
                    misconception_severity = grading["misconception"].get(
                        "severity"
                    )

                update_learner_state(
                    session_id,
                    correct_concepts,
                    missed_concepts,
                    score,
                    misconception_severity
                )

                if confidence_rating is not None:
                    record_metacognitive_checkin(
        session_id,
        concept,
        int(confidence_rating),
    )

                grading["learning_path"] = (
                    optimize_learning_path(
                        session_id,current_concept=concept
                    )
                )

            return jsonify(grading)

    except Exception as e:
        print(
            "QUIZ GRADING ERROR:",
            repr(e)
        )

    # 3. Fallback if AI grading fails
    fallback = {
        "score": 5,
        "feedback": (
            "Unable to grade automatically. "
            "Please compare with sample answer."
        ),
        "correct_concepts": [],
        "missed_concepts": [],
        "study_tip": (
            "Review the sample answer and compare "
            "it against your response."
        )
    }

    if session_id:
        record_quiz_score(
            session_id,
            fallback["score"]
        )

    return jsonify(fallback)

@quiz_bp.route('/quiz/metacognitive', methods=['POST'])
def save_metacognitive_checkin():
    data, parse_error = parse_json_request(request)

    if parse_error:
        return json_error(parse_error)

    session_id = data.get("session_id", "")
    concept = data.get("concept", "")
    confidence_rating = data.get("confidence_rating")

    if not session_id or not concept or confidence_rating is None:
        return json_error("Missing metacognitive check-in data.")

    valid, error = validate_session_id(session_id)
    if not valid:
        return json_error(error)

    try:
        confidence_rating = int(confidence_rating)
    except (TypeError, ValueError):
        return json_error("Confidence rating must be an integer.")

    if confidence_rating not in (1, 2, 3):
        return json_error("Confidence rating must be 1, 2, or 3.")

    record_metacognitive_checkin(
        session_id,
        concept,
        confidence_rating,
    )

    learning_path = optimize_learning_path(
        session_id,
        current_concept=concept,
    )

    return jsonify({
        "success": True,
        "learning_path": learning_path,
    })