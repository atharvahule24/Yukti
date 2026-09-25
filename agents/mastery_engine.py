from db import update_learner_state


def update_mastery_from_assessment(
    session_id: str,
    concept: str,
    score: float,
    correct: bool,
    misconception_severity: str | None = None,
) -> dict:
    """
    Centralized entry point for mastery updates.
    Persistence remains handled by db.update_learner_state().
    """

    correct_concepts = [concept] if correct else []
    missed_concepts = [] if correct else [concept]

    update_learner_state(
        session_id=session_id,
        correct_concepts=correct_concepts,
        missed_concepts=missed_concepts,
        score=score,
        misconception_severity=misconception_severity,
    )

    return {
        "concept": concept,
        "score": score,
        "correct": correct,
        "misconception_severity": misconception_severity,
    }