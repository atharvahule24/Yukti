from db import get_active_misconceptions


def get_adaptive_question_plan(
    session_id: str,
    concept: str | None = None,
    learning_path: dict | None = None,
) -> dict:
    """
    Decide what kind of question the learner should receive next.

    If a learning_path is supplied by the orchestrator, reuse it instead
    of calculating the path again.
    """

    if learning_path is None:
        from agents.path_optimizer import optimize_learning_path

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
    # Unresolved misconception → targeted correction
    # ---------------------------------------------------------
    if misconceptions:
        misconception = max(
            misconceptions,
            key=lambda item: (
                item["occurrences"],
                item["severity"] == "high",
                item["severity"] == "medium",
            ),
        )

        return {
            "concept": target_concept,
            "difficulty": "easy",
            "target": "misconception",
            "question_type": "conceptual",
            "misconception": misconception["misconception"],
            "evidence": misconception["evidence"],
            "severity": misconception["severity"],
            "suggested_intervention": misconception.get(
                "suggested_intervention"
            ),
            "occurrences": misconception.get("occurrences", 1),
            "reason": (
                "The learner has an unresolved misconception. "
                "The next question should directly test that misunderstanding."
            ),
        }

        if learning_path["action"] == "prerequisite_review":
            return {
            "concept": learning_path["concept"],
            "difficulty": learning_path.get("difficulty", "easy"),
            "target": "prerequisite",
            "question_type": "conceptual",
            "reason": learning_path["reason"],
            "target_concept": learning_path.get("target_concept"),
        }

    # ---------------------------------------------------------
    # Step-by-step support
    # ---------------------------------------------------------

    if learning_path["action"] == "prerequisite_review":
        return {
        "concept": learning_path["concept"],
        "difficulty": learning_path.get("difficulty", "easy"),
        "target": "prerequisite",
        "question_type": "conceptual",
        "target_concept": learning_path.get("target_concept"),
        "reason": learning_path.get(
            "reason",
            "A prerequisite concept needs strengthening before continuing."
        ),
    }

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