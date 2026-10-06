from utils.auth import require_session_owner
from difflib import SequenceMatcher
import re
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
    get_active_misconceptions,
)
from agents.path_optimizer import optimize_learning_path
from agents.adaptive_question_engine import get_adaptive_question_plan
from agents.misconception_detector import detect_misconception
from agents.concept_registry import (
    get_canonical_concept,
    get_canonical_concepts,
)

def normalize_question(text):
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def is_similar_question(question, previous_questions, threshold=0.72):
    stop_words = {
        "what", "whats", "is", "are", "do", "does", "did", "the", "a", "an",
        "of", "in", "to", "for", "on", "with", "how", "why", "who", "where",
        "when", "explain", "describe", "define", "compare", "contrast",
        "and", "or"
    }

    def get_keywords(text):
        normalized = normalize_question(text)
        return set(word for word in normalized.split() if word not in stop_words)

    q1_keys = get_keywords(question)
    if not q1_keys:
        return False

    for previous in previous_questions:
        q2_keys = get_keywords(previous)
        if not q2_keys:
            continue

        intersection = len(q1_keys & q2_keys)
        union = len(q1_keys | q2_keys)
        jaccard = intersection / union if union > 0 else 0

        if jaccard >= threshold:
            return True

    return False

quiz_bp = Blueprint('quiz', __name__)

@quiz_bp.route('/quiz/<session_id>', methods=['GET'])
@require_session_owner
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
@require_session_owner
def generate_quiz(session_id):
    valid, error = validate_session_id(session_id)
    if not valid:
        return json_error(error)
    if session_id not in session_store:
        return jsonify({"error": "not_found"}), 404
        
    session_data = session_store[session_id]

    previous_quiz = session_data.get("quiz")
    question_history = session_data.get("quiz_history", [])
    full_text = session_store[session_id].get("full_text", "")

    # Collect questions from previous quiz generations
    previous_questions = []

    for old_quiz in question_history[-5:]:
        if not isinstance(old_quiz, dict):
            continue

        for item in old_quiz.get("mcq", []):
            if isinstance(item, dict):
                question = item.get("question") or item.get("q")
                if question:
                    previous_questions.append(question)

        for item in old_quiz.get("short_answer", []):
            if isinstance(item, dict):
                question = item.get("question") or item.get("q")
                if question:
                    previous_questions.append(question)

    # Also include the currently active quiz
    if previous_quiz:
        for item in previous_quiz.get("mcq", []):
            if isinstance(item, dict):
                question = item.get("question") or item.get("q")
                if question:
                    previous_questions.append(question)

        for item in previous_quiz.get("short_answer", []):
            if isinstance(item, dict):
                question = item.get("question") or item.get("q")
                if question:
                    previous_questions.append(question)

    previous_questions_text = "\n".join(
        f"- {question}" for question in previous_questions
    )

    valid, error = validate_extracted_text(full_text, max_length=None)
    if not valid:
        return jsonify({"error": "no_text"}), 400
    full_text = full_text[:6000]
        
    data, parse_error = parse_json_request(request)
    if parse_error:
        return json_error(parse_error)
    requested_difficulty = data.get("difficulty")
    requested_concept = data.get("concept")

    count, count_error = validate_quiz_count(data.get("count", 5))

    if count_error:
        return json_error(count_error)

    # Get learner-adaptive plan FIRST
    adaptive_context = get_next_learning_action(session_id, concept=requested_concept)
    adaptive_plan = adaptive_context["question_plan"]

    # Adaptive difficulty takes priority when available
    adaptive_difficulty = adaptive_plan.get("difficulty")

    difficulty = adaptive_difficulty or requested_difficulty or "medium"

    print(">>> GENERATING NEW ADAPTIVE QUIZ")
    print(">>> ADAPTIVE PLAN:", adaptive_plan)
    print(">>> DIFFICULTY:", difficulty)

    adaptive_instruction = ""

    if adaptive_plan.get("concept"):
        adaptive_instruction = f"""
    ADAPTIVE LEARNING INSTRUCTIONS

    Target concept:
    {adaptive_plan.get("concept", "")}

    Adaptive target:
    {adaptive_plan.get("target", "")}

    Question type:
    {adaptive_plan.get("question_type", "conceptual")}

    Recommended difficulty:
    {adaptive_plan.get("difficulty", "medium")}

    Reason for this adaptation:
    {adaptive_plan.get("reason", "")}

    PREVIOUSLY ASKED QUESTIONS:
{previous_questions_text if previous_questions_text else "None"}

QUESTION NOVELTY RULES:

- Do NOT repeat any previously asked question.
- Do NOT merely rephrase a previously asked question.
- Create a genuinely different scenario, context, reasoning path, or application.
- The new question must still assess the TARGET CONCEPT and ADAPTIVE TARGET.

    Generate the question so that it follows BOTH the adaptive target
    and the question type.

    QUESTION TYPE RULES:

    1. conceptual
    - Test whether the learner understands the underlying concept.
    - Prefer why, how, comparison, explanation, or interpretation.
    - Do not make the question unnecessarily difficult.

    2. application
    - Give a situation or problem involving the target concept.
    - Require the learner to apply the concept rather than merely define it.
    - Use a meaningful educational context when appropriate.

    3. step_by_step
    - Require the learner to demonstrate the reasoning process.
    - Break the task into manageable stages.
    - Make the intermediate reasoning visible.

    4. recall
    - Test retrieval of an already learned concept.
    - Prefer a definition, fact, formula, relationship, or previously learned idea.
    - Do not introduce substantial new reasoning.

    5. transfer
    - Apply the concept in a new or unfamiliar situation.
    - Do not simply repeat an example used during teaching.
    - Require reasoning or application in the new context.

    ADAPTIVE TARGET RULES:

        If the adaptive target is "misconception":
    - Directly diagnose the identified misconception.
    - The question MUST require the learner to demonstrate whether they understand the underlying issue.
    - Do not merely ask for a definition or ask "what is one negative effect?"
    - Prefer a scenario, comparison, explanation, or reasoning-based question.
    - Create a situation where choosing or explaining the misconception would produce a meaningfully different answer from correct understanding.
    - The learner should need to reason about the concept rather than repeat a fact from the source.
    - Use a NEW question rather than repeating the previous question.
    - Do not reveal the answer.
    - Do not explicitly tell the learner what their misconception is.
    - Do not make the question harder merely because the misconception exists.

    If the adaptive target is "scaffolding":
    - Keep the question manageable.
    - Prefer explicit intermediate reasoning steps.

    If the adaptive target is "example_application":
    - Use a concrete example requiring application of the concept.

    If the adaptive target is "prerequisite":
    - Test the prerequisite concept needed for the current target.
    - Keep the question easy unless otherwise specified.

    If the adaptive target is "retention":
    - Focus on retrieval of the concept rather than introducing new material.

    If the adaptive target is "confidence":
    - Use a clear, solvable conceptual question that lets the learner demonstrate understanding.

    If the adaptive target is "practice":
    - Give a meaningful application problem appropriate to the learner's current level.

    If the adaptive target is "advanced_application":
    - Require deeper reasoning, transfer, or multi-step application.
    """

        if adaptive_plan.get("misconception"):
            adaptive_instruction += f"""

    KNOWN LEARNER MISCONCEPTION:

    Misconception:
    {adaptive_plan.get("misconception", "")}

    Evidence:
    {adaptive_plan.get("evidence", "")}

    Suggested intervention:
    {adaptive_plan.get("suggested_intervention", "")}

    Create a diagnostic question that specifically tests whether the learner
    has corrected this misconception.

    The question must distinguish between:
    A) the learner's previously observed misconception, and
    B) the scientifically/historically supported understanding in the source material.

    The learner must demonstrate reasoning, explanation, comparison, or application
    that reveals which understanding they hold.

    Do NOT simply ask the learner to state the correct fact.

    The question should be answerable using the source material.

    Do NOT:
    - repeat the exact previous question
    - reveal the answer
    - explicitly state the misconception to the learner
    - make the question harder merely because the misconception exists

    The question should provide evidence about whether the learner
    now understands the concept correctly.
    """

        previous_questions = []

        for old_quiz in question_history[-5:]:
            for q in old_quiz.get("mcq", []):
                if q.get("question"):
                    previous_questions.append(q["question"])

            for q in old_quiz.get("short_answer", []):
                if q.get("question"):
                    previous_questions.append(q["question"])

        if previous_quiz:
            for q in previous_quiz.get("mcq", []):
                if q.get("question"):
                    previous_questions.append(q["question"])

            for q in previous_quiz.get("short_answer", []):
                if q.get("question"):
                    previous_questions.append(q["question"])

        previous_questions_text = "\n".join(
            f"- {question}"
            for question in previous_questions[-20:]
        )

    custom_instruction = f"""
    Generate exactly {count} questions.

    IMPORTANT: This is an ADAPTIVE quiz.

    The adaptive learning plan is the primary instruction for question selection.
    The source material is used to ensure factual grounding, but do NOT simply
    generate generic questions from the chapter.

    TARGET CONCEPT:
    {adaptive_plan.get("concept") or "Core concepts from the provided material"}

    ADAPTIVE TARGET:
    {adaptive_plan.get("target", "")}

    QUESTION TYPE:
    {adaptive_plan.get("question_type", "conceptual")}

    REQUIRED DIFFICULTY:
    {difficulty}

    ADAPTIVE REASON:
    {adaptive_plan.get("reason", "")}

    Rules for question generation:

    1. Every question MUST primarily assess the TARGET CONCEPT.

    1a.If the adaptive target is "misconception", the question MUST primarily
   diagnose the specific MISCONCEPTION rather than merely covering the topic.

    2. Every question MUST follow the specified QUESTION TYPE.

    3. Every question MUST satisfy the REQUIRED DIFFICULTY.

    4. Do NOT generate unrelated questions from other concepts in the chapter,
    even if those concepts appear prominently in the source material.

    5. If the adaptive target is "misconception", the question MUST test the
    learner's identified misconception.

    6. If the adaptive target is "advanced_application", the question must
    require transfer, deeper reasoning, or application in a new situation.

    7. If the adaptive target is "practice", the question must require
    application of the target concept.

    8. If the adaptive target is "review", the question should reinforce
    understanding of the target concept.

    9. If the adaptive target is "retention", test retrieval of the target concept.

    10. If the adaptive target is "confidence", use a clear conceptual question
        that allows the learner to demonstrate understanding.

    11. Do not merely copy sentences or questions from the source material.

    12. When generating multiple questions, vary the scenario, wording, and
        reasoning while keeping the same target concept.

    Difficulty rules:
    - easy = direct recall, simple conceptual understanding, or straightforward reasoning
    - medium = explanation, comparison, application, or moderate reasoning
    - hard = analysis, transfer, multi-step reasoning, or complex application

    For HARD questions:
    - Do NOT ask simple definition questions.
    - Do NOT ask direct identification questions.
    - Require application, comparison, explanation, analysis, or reasoning.

    Every question MUST contain:
    - a non-empty concept
    - a difficulty field
    - difficulty exactly equal to "{difficulty}"

    {f'Every generated question MUST use:\n    concept = "{adaptive_plan["concept"]}"' if adaptive_plan.get("concept") else 'Every generated question MUST identify a specific, non-empty concept tested from the material.'}

    Never return null or empty concept.
    Never label a simple recall question as hard.

    """ + adaptive_instruction
    
    generator = Generator(json_mode=True)
    try:
        def generate_and_filter(prompt_template, existing_qs, target_count, key_name):
            valid_questions = []
            seen = list(existing_qs)
            attempts = 0
            
            while len(valid_questions) < target_count and attempts < 3:
                needed = target_count - len(valid_questions)
                current_instruction = custom_instruction.replace(
                    f"Generate exactly {count} questions.", 
                    f"Generate exactly {needed} questions."
                )
                prompt = prompt_template + current_instruction
                
                try:
                    raw = generator.chain.invoke({"context": full_text, "question": prompt})
                    from utils.json_helper import extract_json
                    res = extract_json(raw)
                    if res and key_name in res:
                        for q in res[key_name]:
                            q_text = q.get("question", "")
                            if q_text and not is_similar_question(q_text, seen):
                                valid_questions.append(q)
                                seen.append(q_text)
                                if len(valid_questions) == target_count:
                                    break
                except Exception as e:
                    print("Generation loop error:", repr(e))
                attempts += 1
                
            if len(valid_questions) < target_count:
                raise RuntimeError(
                    f"Insufficient novel questions generated for {key_name}. "
                    f"Requested {target_count}, but only {len(valid_questions)} met novelty and adaptive constraints after {attempts} attempts."
                )
                
            return {key_name: valid_questions}

        mcq = generate_and_filter(QUIZ_MCQ_PROMPT, previous_questions, count, "mcq")
        
        # Combine previous questions with newly generated MCQs to ensure SAs don't overlap with MCQs
        mcq_questions = [q.get("question", "") for q in mcq.get("mcq", [])]
        sa = generate_and_filter(QUIZ_SHORT_ANSWER_PROMPT, previous_questions + mcq_questions, count, "short_answer")

        previous_questions = []

        for old_quiz in question_history:
            for q in old_quiz.get("mcq", []):
                if q.get("question"):
                    previous_questions.append(q["question"])

            for q in old_quiz.get("short_answer", []):
                if q.get("question"):
                    previous_questions.append(q["question"])

        if previous_quiz:
            for q in previous_quiz.get("mcq", []):
                if q.get("question"):
                    previous_questions.append(q["question"])

            for q in previous_quiz.get("short_answer", []):
                if q.get("question"):
                    previous_questions.append(q["question"])

        adaptive_concept = adaptive_plan.get("concept")

        for i, m in enumerate(mcq.get("mcq", [])):
            m["id"] = f"mcq_{i}"

            concept = adaptive_concept or m.get("concept")
            if not concept:
                raise ValueError("Generated MCQ is missing concept.")

            m["concept"] = get_canonical_concept(str(concept))
            m["difficulty"] = difficulty

            if not m["concept"]:
                raise ValueError("Generated MCQ has invalid concept.")


        for i, s in enumerate(sa.get("short_answer", [])):
            s["id"] = f"sa_{i}"

            concept = adaptive_concept or s.get("concept")
            if not concept:
                raise ValueError("Generated short-answer question is missing concept.")

            s["concept"] = get_canonical_concept(str(concept))
            s["difficulty"] = difficulty

            if not s["concept"]:
                raise ValueError("Generated short-answer question has invalid concept.")
            
        quiz = {
            "mcq": mcq.get("mcq", []),
            "short_answer": sa.get("short_answer", [])
        }

        # Preserve the previously generated quiz before replacing it.
        if previous_quiz:
            question_history.append(previous_quiz)

        # Keep only the most recent 5 quiz generations
        session_data["quiz_history"] = question_history[-5:]

        # Store the newly generated quiz as the active quiz.
        session_data["quiz"] = quiz

        session_store[session_id] = session_data

        return jsonify({
            **quiz,
            "adaptive_plan": adaptive_plan,
            "adaptive_context": adaptive_context,
        })

    except RuntimeError as e:
        return json_error(str(e))
    except Exception as e:
        print("🔥 QUIZ GENERATION ERROR:", repr(e))
        raise

@quiz_bp.route('/quiz/reassess/<session_id>', methods=['POST'])
@require_session_owner
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
        misconceptions = get_active_misconceptions(
            session_id,
            concept
        )

        active_misconception = (
            misconceptions[0] if misconceptions else {}
        )

        prompt = TARGETED_REASSESSMENT_PROMPT.format(
            concept=concept,
            misconception=active_misconception.get(
                "misconception", ""
            ),
            evidence=active_misconception.get(
                "evidence", ""
            ),
            suggested_intervention=active_misconception.get(
                "suggested_intervention", ""
            ),
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
            "message": str(e)
        }), 500

@quiz_bp.route('/quiz/grade', methods=['POST'])
@require_session_owner
def grade_answer():
    data, parse_error = parse_json_request(request)

    if parse_error:
        return json_error(parse_error)

    confidence_rating = data.get("confidence_rating")
    is_reassessment = data.get("is_reassessment", False)

    question = data.get("question") or ""
    user_answer = data.get("user_answer") or ""
    sample_answer = data.get("sample_answer") or ""

    concept_input = data.get("concept")
    targeted_misconception = data.get("misconception")
    targeted_misconception_text = None
    if targeted_misconception:
        if isinstance(targeted_misconception, dict):
            targeted_misconception_text = targeted_misconception.get("misconception")
        else:
            targeted_misconception_text = str(targeted_misconception)

    if not targeted_misconception_text and is_reassessment:
        active = get_active_misconceptions(session_id, concept_input or "")
        if active:
            targeted_misconception_text = active[0].get("misconception")

    if concept_input:
        concept = get_canonical_concept(str(concept_input))
    else:
        concept = ""

    if not concept:
        return json_error(
        "Quiz question is missing a concept. Please generate the quiz again."
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

            mastery_result = update_mastery_from_assessment(
                session_id=session_id,
                concept=concept,
                score=grading["score"],
                correct=True,
            )
            grading["mastery_update"] = mastery_result

            if is_reassessment:
                resolve_misconceptions(
                    session_id=session_id,
                    concept=concept,
                    misconception_text=targeted_misconception_text,
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

        raw_score = grading.get("score", 0)
        try:
            score = float(raw_score)
        except (ValueError, TypeError):
            match = re.search(r"(\d+(\.\d+)?)", str(raw_score))
            score = float(match.group(1)) if match else 0.0
            
        grading["score"] = score

        # Detect misconception for incorrect answers.
        print("🔥 SCORE DEBUG:", score, "IS_REASSESSMENT:", is_reassessment)
        if score < 7:
            misconception_result = detect_misconception(
                question=question,
                student_answer=user_answer,
                sample_answer=sample_answer,
                concept=concept,
            )

            print("🔎 MISCONCEPTION RESULT:", misconception_result)

            grading["misconception"] = misconception_result

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
                    misconception_text=targeted_misconception_text,
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
@require_session_owner
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
@require_session_owner
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
    misconception_payload = data.get("misconception")
    targeted_misconception_text = None
    
    if misconception_payload:
        if isinstance(misconception_payload, dict):
            targeted_misconception_text = misconception_payload.get("misconception")
        else:
            targeted_misconception_text = str(misconception_payload)
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
        if correct and score >= 7 and targeted_misconception_text:
            resolve_misconceptions(
                session_id=session_id,
                concept=concept,
                misconception_text=targeted_misconception_text
            )

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