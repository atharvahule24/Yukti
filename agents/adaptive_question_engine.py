from db import get_learner_state, get_active_misconceptions
from agents.path_optimizer import optimize_learning_path


def get_adaptive_question_plan(
    session_id: str,
    concept: str | None = None,
) -> dict:
    """
    Decide what kind of question the learner should receive next
    based on learner state, misconceptions, and the path optimizer.
    """

    learning_path = optimize_learning_path(
        session_id=session_id,
        current_concept=concept,
    )

    target_concept = learning_path.get("concept") or concept

    if not target_concept:
        return {
            "concept": None,
            "difficulty": "medium",
            "target": "new_learning",
            "question_type": "conceptual",
            "reason": "No learner state is available yet.",
        }

    misconceptions = get_active_misconceptions(
        session_id,
        target_concept,
    )

    # ---------------------------------------------------------
    # Repeated misconception → targeted conceptual question
    # ---------------------------------------------------------
    if misconceptions:
        misconception = max(
            misconceptions,
            key=lambda item: item["occurrences"],
        )

        return {
            "concept": target_concept,
            "difficulty": "easy",
            "target": "misconception",
            "question_type": "conceptual",
            "misconception": misconception["misconception"],
            "evidence": misconception["evidence"],
            "severity": misconception["severity"],
            "reason": (
                "The learner has an unresolved misconception. "
                "The next question should directly test that "
                "misunderstanding."
            ),
        }

    # ---------------------------------------------------------
    # Step-by-step support
    # ---------------------------------------------------------
    if learning_path["action"] == "step_by_step_review":
        return {
            "concept": target_concept,
            "difficulty": "easy",
            "target": "scaffolding",
            "question_type": "step_by_step",
            "reason": learning_path["reason"],
        }

    # ---------------------------------------------------------
    # Example-based reinforcement
    # ---------------------------------------------------------
    if learning_path["action"] == "example_based_review":
        return {
            "concept": target_concept,
            "difficulty": "easy",
            "target": "example_application",
            "question_type": "application",
            "reason": learning_path["reason"],
        }

    # ---------------------------------------------------------
    # Confidence reinforcement
    # ---------------------------------------------------------
    if learning_path["action"] == "confidence_reinforcement":
        return {
            "concept": target_concept,
            "difficulty": "medium",
            "target": "confidence",
            "question_type": "conceptual",
            "reason": learning_path["reason"],
        }

    # ---------------------------------------------------------
    # Generic review / practice / advance
    # ---------------------------------------------------------
    return {
        "concept": target_concept,
        "difficulty": learning_path.get("difficulty", "medium"),
        "target": learning_path["action"],
        "question_type": (
            "application"
            if learning_path["action"] == "practice"
            else "conceptual"
        ),
        "reason": learning_path["reason"],
    }