from agents.adaptive_orchestrator import get_next_learning_action
from flask import Blueprint, jsonify, request
from agents.mastery_engine import update_mastery_from_assessment
from routes.store import session_store
from llm.generator import Generator
from agents.prompts import (
    QUIZ_MCQ_PROMPT,
    QUIZ_SHORT_ANSWER_PROMPT,
    TARGETED_REASSESSMENT_PROMPT,
)
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
    record_metacognitive_checkin,
    record_misconception,
    resolve_misconceptions,
)
from agents.path_optimizer import optimize_learning_path
from agents.adaptive_question_engine import get_adaptive_question_plan
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
    difficulty = data.get("difficulty", "medium")
    count, count_error = validate_quiz_count(data.get("count", 5))

    if count_error:
        return json_error(count_error)

    adaptive_context = get_next_learning_action(session_id)
    adaptive_plan = adaptive_context["question_plan"]

    adaptive_instruction = ""

    if adaptive_plan.get("concept"):
        adaptive_instruction = f"""
    Adapt the quiz to the learner's current learning state.

    Target concept: {adaptive_plan["concept"]}
    Adaptive target: {adaptive_plan["target"]}
    Question style: {adaptive_plan["question_type"]}
    Recommended difficulty: {adaptive_plan["difficulty"]}

    Reason for this adaptation:
    {adaptive_plan["reason"]}
    """

        if adaptive_plan.get("misconception"):
            adaptive_instruction += f"""
    Known learner misconception:
    {adaptive_plan["misconception"]}

    Evidence:
    {adaptive_plan.get("evidence", "")}

    Create questions that specifically test whether the learner
    understands this misconception correctly.
    Do not reveal the answer in the question.
    """

    custom_instruction = f"""
    Ensure the difficulty is {difficulty}.
    Generate exactly {count} questions.
    """ + adaptive_instruction
    
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
            m["concept"] = adaptive_plan.get("concept")
            
        for i, s in enumerate(sa.get("short_answer", [])):
            s["id"] = f"sa_{i}"
            s["concept"] = adaptive_plan.get("concept")
            
        quiz = {"mcq": mcq.get("mcq", []), "short_answer": sa.get("short_answer", [])}
        session_data = session_store[session_id]
        session_data["quiz"] = quiz
        session_store[session_id] = session_data
        return jsonify({**quiz,"adaptive_plan": adaptive_plan,"adaptive_context": adaptive_context,})
    except Exception as e:
        return jsonify({"error": "generation_failed", "message": str(e)}), 500

@quiz_bp.route('/quiz/reassess/<session_id>', methods=['POST'])
def generate_reassessment(session_id):
    valid, error = validate_session_id(session_id)

    if not valid:
        return json_error(error)

    if session_id not in session_store:
        return jsonify({"error": "not_found"}), 404

    data, parse_error = parse_json_request(request)

    if parse_error:
        return json_error(parse_error)

    concept = data.get("concept", "").strip()

    if not concept:
        return json_error("Concept is required.")

    full_text = session_store[session_id].get("full_text", "")

    valid, error = validate_extracted_text(full_text, max_length=None)

    if not valid:
        return jsonify({"error": "no_text"}), 400

    generator = Generator(json_mode=True)

    try:
        prompt = TARGETED_REASSESSMENT_PROMPT.format(
            concept=concept
        )

        res = generator.chain.invoke({
            "context": full_text[:6000],
            "question": prompt,
        })

        reassessment = extract_json(res)

        if not reassessment:
            return jsonify({
                "error": "generation_failed"
            }), 500

        questions = reassessment.get("short_answer", [])

        if not questions:
            return jsonify({
                "error": "generation_failed"
            }), 500

        question = questions[0]
        question["id"] = f"reassess_{concept}"

        return jsonify(question)

    except Exception as e:
        return jsonify({
            "error": "generation_failed",
            "message": str(e),
        }), 500

@quiz_bp.route('/quiz/grade', methods=['POST'])
def grade_answer():
    data, parse_error = parse_json_request(request)

    if parse_error:
        return json_error(parse_error)

    confidence_rating = data.get("confidence_rating")
    is_reassessment = data.get("is_reassessment", False)

    question = data.get("question") or ""
    user_answer = data.get("user_answer") or ""
    sample_answer = data.get("sample_answer") or ""

    concept_input = data.get("concept") or question or ""
    concept = get_canonical_concept(concept_input)
    

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

            mastery_result = update_mastery_from_assessment(
                session_id=session_id,
                concept=concept,
                score=grading["score"],
                correct=True,
            )
            grading["mastery_update"] = mastery_result

            if confidence_rating is not None:
                record_metacognitive_checkin(
                    session_id,
                    concept,
                    int(confidence_rating),
                )

            if is_reassessment or confidence_rating is not None:
                grading["learning_path"] = optimize_learning_path(
                    session_id,
                    current_concept=concept
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

        print(
            "EXTRACTED GRADING:",
            repr(grading)
        )

        if not grading:
            raise ValueError(
                "AI grading response could not be parsed as JSON."
            )

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

        score = float(
            grading.get("score", 0) or 0
        )

        # Detect misconception for incorrect answers.
        if score < 7:
            grading["misconception"] = detect_misconception(
                question=question,
                student_answer=user_answer,
                sample_answer=sample_answer,
                concept=concept,
            )

        # Update persistent learner data
        # only when a valid session exists.
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
                    correct_concepts.append(concept)
                else:
                    missed_concepts.append(concept)

            misconception_severity = None

            if grading.get("misconception"):
                misconception_severity = (
                    grading["misconception"].get("severity")
                )

            mastery_result = update_mastery_from_assessment(
                session_id=session_id,
                concept=concept,
                score=score,
                correct=score >= 7,
                misconception_severity=misconception_severity,
            )

            grading["mastery_update"] = mastery_result

            misconception = grading.get("misconception")

            if misconception and isinstance(misconception, dict):
                record_misconception(
                    session_id=session_id,
                    concept=concept,
                    severity=misconception.get("severity", "medium"),
                    misconception=misconception.get(
                        "misconception",
                        "unspecified_misconception",
                    ),
                    evidence=misconception.get("evidence"),
                    suggested_intervention=misconception.get(
                        "suggested_intervention"
                    ),
                )

            if is_reassessment and score >= 7:
                resolve_misconceptions(
                    session_id=session_id,
                    concept=concept,
                )

            if confidence_rating is not None:
                record_metacognitive_checkin(
                    session_id,
                    concept,
                    int(confidence_rating),
                )

            if is_reassessment or confidence_rating is not None:
                grading["learning_path"] = optimize_learning_path(
                    session_id,
                    current_concept=concept
                )

        return jsonify(grading)

    except Exception as e:
        print(
            "QUIZ GRADING ERROR:",
            repr(e)
        )

        return jsonify({
            "error": "server_error",
            "message": str(e)
        }), 500

@quiz_bp.route('/quiz/metacognitive', methods=['POST'])
def save_metacognitive_checkin():
    data, parse_error = parse_json_request(request)

    if parse_error:
        return json_error(parse_error)

    session_id = data.get("session_id", "")
    concept = data.get("concept", "")
    confidence_rating = data.get("confidence_rating")

    if not session_id or confidence_rating is None:
        return json_error("Missing metacognitive check-in data.")
    concept = concept or "general"

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

@quiz_bp.route('/quiz/intervention-grade', methods=['POST'])
def grade_intervention_answer():
    """
    Grade the learner's answer to a checking question inside an
    adaptive intervention, then feed the result back into learner state.
    """
    data, parse_error = parse_json_request(request)
    if parse_error:
        return json_error(parse_error)

    session_id = data.get("session_id", "")
    concept_input = data.get("concept", "")
    question = data.get("question", "")
    user_answer = data.get("user_answer", "")
    misconception = data.get("misconception")

    if not session_id or not question or not user_answer:
        return json_error("session_id, question and user_answer are required")

    valid, error = validate_session_id(session_id)
    if not valid:
        return json_error(error)

    session_data = session_store.get(session_id, {})
    context = session_data.get("full_text", "")

    concept = get_canonical_concept(concept_input or "general")

    grading_prompt = f"""
You are evaluating a student's answer to a checking question
inside an adaptive learning intervention.

Concept: {concept}

Original learning context:
{context[:12000]}

Checking question:
{question}

Student answer:
{user_answer}

Evaluate whether the student now demonstrates the concept correctly.

Return ONLY valid JSON:
{{
  "score": 0,
  "correct": false,
  "feedback": "specific explanation",
  "misconception": "the remaining misunderstanding, or null",
  "severity": "low",
  "study_tip": "one specific next step"
}}

Scoring:
8-10 = concept is demonstrated correctly
7 = acceptable understanding with minor gaps
4-6 = partial understanding / important misconception remains
0-3 = incorrect understanding

Be strict about the actual concept. Do not give credit merely because
the student used relevant terminology.
"""

    try:
        generator = Generator(json_mode=True)

        result = generator.chain.invoke({
            "context": context[:12000],
            "question": grading_prompt,
        })

        grading = extract_json(result)

        if not grading:
            return jsonify({
                "error": "intervention_grading_failed"
            }), 500

        score = float(grading.get("score", 0))
        correct = bool(grading.get("correct", score >= 7))
        severity = grading.get("severity") or "medium"
        detected_misconception = grading.get("misconception")

        # Update learner mastery exactly once.
        update_mastery_from_assessment(
            session_id=session_id,
            concept=concept,
            score=score,
            correct=correct,
            misconception_severity=(
                None if correct else severity
            ),
        )

        # Successful intervention = resolve the active misconception.
        if correct and score >= 7:
            resolve_misconceptions(session_id, concept)

        # Failed intervention = retain/update misconception memory.
        elif detected_misconception:
            record_misconception(
                session_id=session_id,
                concept=concept,
                severity=severity,
                misconception=detected_misconception,
                evidence=grading.get("feedback"),
                suggested_intervention=grading.get("study_tip"),
            )

        learning_path = optimize_learning_path(
            session_id=session_id,
            current_concept=concept,
        )

        return jsonify({
            "score": score,
            "correct": correct,
            "feedback": grading.get("feedback", ""),
            "study_tip": grading.get("study_tip", ""),
            "misconception": detected_misconception,
            "learning_path": learning_path,
            "resolved": bool(correct and score >= 7),
        })

    except Exception as e:
        return jsonify({
            "error": "intervention_grading_failed",
            "message": str(e),
        }), 500