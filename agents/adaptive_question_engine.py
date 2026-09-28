from db import get_active_misconceptions


def get_adaptive_question_plan(
    session_id: str,
    concept: str | None = None,
    learning_path: dict | None = None,
) -> dict:
    """
    Decide what kind of question the learner should receive next.

    The path optimizer decides WHAT the learner needs next.
    This module converts that decision into a question strategy:
    - concept
    - difficulty
    - target
    - question type
    - misconception focus
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

    # ---------------------------------------------------------
    # 1. Unresolved misconception
    # ---------------------------------------------------------
    misconceptions = get_active_misconceptions(
        session_id,
        target_concept,
    )

    if misconceptions:
        misconception = max(
            misconceptions,
            key=lambda item: (
                item.get("occurrences", 1),
                item.get("severity") == "high",
                item.get("severity") == "medium",
            ),
        )

        return {
            "concept": target_concept,
            "difficulty": "easy",
            "target": "misconception",
            "question_type": "conceptual",
            "misconception": misconception.get("misconception"),
            "evidence": misconception.get("evidence"),
            "severity": misconception.get("severity", "medium"),
            "suggested_intervention": misconception.get(
                "suggested_intervention"
            ),
            "occurrences": misconception.get("occurrences", 1),
            "reason": (
                "The learner has an unresolved misconception. "
                "The next question should directly test that misunderstanding."
            ),
        }

    action = learning_path.get("action", "review")
    difficulty = learning_path.get("difficulty", "medium")
    reason = learning_path.get(
        "reason",
        "The learner needs additional practice with this concept.",
    )

    # ---------------------------------------------------------
    # 2. Prerequisite review
    # ---------------------------------------------------------
    if action == "prerequisite_review":
        return {
            "concept": learning_path.get("concept") or target_concept,
            "difficulty": "easy",
            "target": "prerequisite",
            "question_type": "conceptual",
            "target_concept": learning_path.get("target_concept"),
            "reason": reason,
        }

    # ---------------------------------------------------------
    # 3. Step-by-step support
    # ---------------------------------------------------------
    if action == "step_by_step_review":
        return {
            "concept": target_concept,
            "difficulty": "easy",
            "target": "scaffolding",
            "question_type": "step_by_step",
            "reason": reason,
        }

    # ---------------------------------------------------------
    # 4. Example-based reinforcement
    # ---------------------------------------------------------
    if action == "example_based_review":
        return {
            "concept": target_concept,
            "difficulty": "easy",
            "target": "example_application",
            "question_type": "application",
            "reason": reason,
        }

    # ---------------------------------------------------------
    # 5. Spaced review
    # ---------------------------------------------------------
    if action == "spaced_review":
        return {
            "concept": target_concept,
            "difficulty": difficulty,
            "target": "retention",
            "question_type": "recall",
            "reason": reason,
        }

    # ---------------------------------------------------------
    # 6. Confidence reinforcement
    # ---------------------------------------------------------
    if action == "confidence_reinforcement":
        return {
            "concept": target_concept,
            "difficulty": "medium",
            "target": "confidence",
            "question_type": "conceptual",
            "reason": reason,
        }

    # ---------------------------------------------------------
    # 7. Review
    # ---------------------------------------------------------
    if action == "review":
        return {
            "concept": target_concept,
            "difficulty": difficulty,
            "target": "review",
            "question_type": "conceptual",
            "reason": reason,
        }

    # ---------------------------------------------------------
    # 8. Practice
    # ---------------------------------------------------------
    if action == "practice":
        return {
            "concept": target_concept,
            "difficulty": difficulty,
            "target": "practice",
            "question_type": "application",
            "reason": reason,
        }

    # ---------------------------------------------------------
    # 9. Advance
    # ---------------------------------------------------------
    if action == "advance":
        return {
            "concept": target_concept,
            "difficulty": difficulty,
            "target": "advanced_application",
            "question_type": "transfer",
            "reason": (
                "The learner has demonstrated sufficient understanding "
                "to move toward a more challenging application."
            ),
        }

    # ---------------------------------------------------------
    # 10. Safe fallback
    # ---------------------------------------------------------
    return {
        "concept": target_concept,
        "difficulty": difficulty,
        "target": action,
        "question_type": "conceptual",
        "reason": reason,
    }