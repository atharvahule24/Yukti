from agents.adaptive_question_engine import get_adaptive_question_plan
from agents.path_optimizer import optimize_learning_path


def get_next_learning_action(
    session_id: str,
    concept: str | None = None,
) -> dict:
    """
    Central coordinator for the adaptive learning loop.

    The orchestrator calculates the learning path once and passes that
    decision into the adaptive question engine.
    """

    learning_path = optimize_learning_path(
        session_id=session_id,
        current_concept=concept,
    )

    question_plan = get_adaptive_question_plan(
        session_id=session_id,
        concept=concept,
        learning_path=learning_path,
    )

    return {
        "learning_path": learning_path,
        "question_plan": question_plan,
        "next_action": learning_path.get("action"),
        "concept": question_plan.get("concept") or concept,
        "difficulty": question_plan.get("difficulty", "medium"),
        "question_type": question_plan.get(
            "question_type",
            "conceptual",
        ),
        "reason": question_plan.get(
            "reason",
            learning_path.get("reason", ""),
        ),
    }