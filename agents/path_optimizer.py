from db import get_learner_state


def optimize_learning_path(session_id: str) -> dict:
    """
    Select the next learning action based on the learner's
    weakest concept.
    """

    states = get_learner_state(session_id)

    if not states:
        return {
            "action": "learn",
            "reason": "No learner performance data available yet.",
            "concept": None,
            "difficulty": "medium",
        }

    weakest = states[0]
    concept = weakest["concept"]
    mastery = weakest["mastery_score"]

    if mastery < 40:
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
        "difficulty": difficulty,
    }