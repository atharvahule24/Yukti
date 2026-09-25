from db import (
    get_learner_state,
    get_latest_metacognitive_checkin,
    get_active_misconceptions,
)

from agents.concept_registry import (
    get_prerequisites,
    get_canonical_concept,
)


def optimize_learning_path(
    session_id: str,
    current_concept: str | None = None,
) -> dict:
    student_confidence = None

    if current_concept:
        student_confidence = get_latest_metacognitive_checkin(
            session_id,
            current_concept,
        )

    # Keep ALL learner states available.
    # We need them for prerequisite mastery lookup.
    all_states = get_learner_state(session_id)

    # ---------------------------------------------------------
    # 1. Determine which state we are optimizing.
    # ---------------------------------------------------------
    states = all_states

    if current_concept:
        current_states = [
            state
            for state in all_states
            if state["concept"].lower() == current_concept.lower()
        ]

        if current_states:
            states = current_states

    # ---------------------------------------------------------
    # 2. No learner state yet -> check prerequisites first.
    # ---------------------------------------------------------
    if not states and current_concept:
        prerequisites = get_prerequisites(current_concept)

        if prerequisites:
            state_map = {
                get_canonical_concept(item["concept"]): item
                for item in all_states
            }

            weak_prerequisites = []

            for prerequisite in prerequisites:
                prerequisite_state = state_map.get(
                    get_canonical_concept(prerequisite)
                )

                mastery = (
                    prerequisite_state.get("mastery", 0)
                    if prerequisite_state
                    else 0
                )

                confidence = (
                    prerequisite_state.get("confidence", 0)
                    if prerequisite_state
                    else 0
                )

                weak_prerequisites.append({
                    "concept": prerequisite,
                    "mastery": mastery,
                    "confidence": confidence,
                })

            weak_prerequisites.sort(
                key=lambda item: (
                    item["mastery"],
                    item["confidence"],
                )
            )

            weakest_prerequisite = weak_prerequisites[0]

            if weakest_prerequisite["mastery"] < 70:
                return {
                    "action": "prerequisite_review",
                    "reason": (
                        f"{current_concept} depends on "
                        f"{weakest_prerequisite['concept']}, which currently "
                        f"has {weakest_prerequisite['mastery']:.0f}% mastery. "
                        "Strengthen the prerequisite before continuing."
                    ),
                    "concept": weakest_prerequisite["concept"],
                    "target_concept": current_concept,
                    "mastery": weakest_prerequisite["mastery"],
                    "confidence": weakest_prerequisite["confidence"],
                    "difficulty": (
                        "easy"
                        if weakest_prerequisite["mastery"] < 40
                        else "medium"
                    ),
                }

        return {
            "action": "learn",
            "reason": "No learner performance data available for the requested concept yet.",
            "concept": current_concept,
            "difficulty": "medium",
        }

    # ---------------------------------------------------------
    # 3. Find weakest concept in the current learning scope.
    # ---------------------------------------------------------
    weakest_state = min(
        states,
        key=lambda state: (
            state["mastery"],
            state["confidence"],
        ),
    )

    # ---------------------------------------------------------
    # 4. Check persistent misconception memory.
    #
    # Repeated unresolved misconceptions should receive
    # priority over generic review.
    # ---------------------------------------------------------
    misconceptions = get_active_misconceptions(
        session_id,
        weakest_state["concept"],
    )

    if misconceptions:
        repeated = max(
            misconceptions,
            key=lambda item: (
                item["occurrences"],
                item["severity"] == "high",
                item["severity"] == "medium",
            ),
        )

        if repeated["occurrences"] >= 2 or repeated["severity"] == "high":
            return {
                "action": "targeted_misconception_review",
                "reason": (
                    f"An unresolved misconception has been detected "
                    f"{repeated['occurrences']} time(s) for "
                    f"{weakest_state['concept']}. Targeted correction "
                    f"is recommended before moving forward."
                ),
                "concept": weakest_state["concept"],
                "mastery": weakest_state["mastery"],
                "confidence": weakest_state["confidence"],
                "difficulty": "easy",
                "misconception": repeated["misconception"],
                "evidence": repeated["evidence"],
                "severity": repeated["severity"],
                "suggested_intervention": repeated["suggested_intervention"],
                "occurrences": repeated["occurrences"],
            }

    # ---------------------------------------------------------
    # 5. Prerequisite-aware adaptation.
    #
    # IMPORTANT:
    # Use ALL learner states here, not the filtered current
    # concept states.
    # ---------------------------------------------------------
    if current_concept:
        prerequisites = get_prerequisites(current_concept)

        if prerequisites:
            state_map = {
                get_canonical_concept(item["concept"]): item
                for item in all_states
            }

            weak_prerequisites = []

            for prerequisite in prerequisites:
                prerequisite_state = state_map.get(
                    get_canonical_concept(prerequisite)
                )

                mastery = (
                    prerequisite_state.get("mastery", 0)
                    if prerequisite_state
                    else 0
                )

                confidence = (
                    prerequisite_state.get("confidence", 0)
                    if prerequisite_state
                    else 0
                )

                weak_prerequisites.append(
                    {
                        "concept": prerequisite,
                        "mastery": mastery,
                        "confidence": confidence,
                    }
                )

            weak_prerequisites.sort(
                key=lambda item: (
                    item["mastery"],
                    item["confidence"],
                )
            )

            weakest_prerequisite = weak_prerequisites[0]

            if weakest_prerequisite["mastery"] < 70:
                return {
                    "action": "prerequisite_review",
                    "reason": (
                        f"{current_concept} depends on "
                        f"{weakest_prerequisite['concept']}, which currently "
                        f"has {weakest_prerequisite['mastery']:.0f}% mastery. "
                        "Strengthen the prerequisite before continuing."
                    ),
                    "concept": weakest_prerequisite["concept"],
                    "target_concept": current_concept,
                    "mastery": weakest_prerequisite["mastery"],
                    "confidence": weakest_prerequisite["confidence"],
                    "difficulty": (
                        "easy"
                        if weakest_prerequisite["mastery"] < 40
                        else "medium"
                    ),
                }

    # ---------------------------------------------------------
    # 6. Metacognitive signal:
    # Low performance + high confidence can indicate a
    # misconception or misunderstanding.
    # ---------------------------------------------------------
    if student_confidence is not None:
        if (
            weakest_state["recent_score"] <= 7
            and student_confidence == 3
        ):
            return {
                "action": "targeted_misconception_review",
                "reason": (
                    "Low recent performance with high self-reported "
                    "confidence suggests the student may need targeted "
                    "misconception correction."
                ),
                "concept": weakest_state["concept"],
                "mastery": weakest_state["mastery"],
                "confidence": weakest_state["confidence"],
                "difficulty": "easy",
            }

        # -----------------------------------------------------
        # 7. Low mastery + low confidence -> scaffolding.
        # -----------------------------------------------------
        if (
            weakest_state["mastery"] < 50
            and student_confidence == 1
        ):
            return {
                "action": "step_by_step_review",
                "reason": (
                    "Low mastery with low self-reported confidence "
                    "suggests the student needs additional scaffolding."
                ),
                "concept": weakest_state["concept"],
                "mastery": weakest_state["mastery"],
                "confidence": weakest_state["confidence"],
                "difficulty": "easy",
            }

        # -----------------------------------------------------
        # 8. High performance + low confidence -> reinforce
        # confidence rather than unnecessarily reteaching.
        # -----------------------------------------------------
        if (
            weakest_state["recent_score"] >= 8
            and student_confidence == 1
        ):
            return {
                "action": "confidence_reinforcement",
                "reason": (
                    "Strong recent performance with low self-reported "
                    "confidence suggests the student may understand the "
                    "concept better than they believe."
                ),
                "concept": weakest_state["concept"],
                "mastery": weakest_state["mastery"],
                "confidence": weakest_state["confidence"],
                "difficulty": "medium",
            }

    # ---------------------------------------------------------
    # 9. Prioritize concepts that explicitly need support.
    # ---------------------------------------------------------
    support_states = [
        state
        for state in states
        if state["needs_examples"] or state["needs_step_by_step"]
    ]

    candidates = support_states if support_states else states

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

    # ---------------------------------------------------------
    # 10. Choose intervention based on learner state.
    # ---------------------------------------------------------
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