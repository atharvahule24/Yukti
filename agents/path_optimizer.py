from db import get_learner_state
from agents.concept_registry import get_canonical_concepts


def optimize_learning_path(session_id: str, current_concept: str | None = None) -> dict:
    states = get_learner_state(session_id)
    if current_concept:
        current_states = [
            state for state in states
            if state["concept"].lower() == current_concept.lower()
        ]

        if current_states:
            states = current_states    

    if not states:
        return {
            "action": "learn",
            "reason": "No learner performance data available yet.",
            "concept": None,
            "difficulty": "medium",
        }

    # Prioritize concepts that explicitly need additional support.
    support_states = [
        state
        for state in states
        if state["needs_examples"] or state["needs_step_by_step"]
    ]

    candidates = support_states if support_states else states

    # Among candidates, prioritize:
    # 1. Lowest mastery
    # 2. Lowest confidence
    weakest = min(
        candidates,
        key=lambda state: (
            state["mastery"],
            state["confidence"],
        ),
    )

    concept = weakest["concept"]
    mastery = weakest["mastery"]
    confidence = weakest["confidence"]

    if weakest["needs_step_by_step"]:
        action = "step_by_step_review"
        difficulty = "easy"
        reason = (
            f"Step-by-step support needed for {concept} "
            f"due to low mastery and confidence."
        )

    elif weakest["needs_examples"]:
        action = "example_based_review"
        difficulty = "easy"
        reason = (
            f"Additional examples needed for {concept} "
            f"due to low mastery and confidence."
        )

    elif mastery < 40:
        action = "review"
        difficulty = "easy"
        reason = f"Low mastery detected for {concept}."

    elif mastery < 70:
        action = "practice"
        difficulty = "medium"
        reason = f"Partial mastery detected for {concept}."

    else:
        action = "advance"
        difficulty = "hard"
        reason = f"Strong mastery detected for {concept}."

    return {
        "action": action,
        "reason": reason,
        "concept": concept,
        "mastery": mastery,
        "confidence": confidence,
        "difficulty": difficulty,
    }