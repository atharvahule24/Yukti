import re
from typing import Any


def extract_question_criteria(
    question: str,
    sample_answer: str = "",
    concept: str = "",
    explicit_criteria: list[dict | str] | None = None,
) -> list[dict[str, Any]]:
    """
    Extract or normalize criterion-based grading rubrics for a short-answer question.
    Returns a list of dicts: [{"criterion": str, "max_points": float}].
    Total max_points across all criteria is normalized to 10.0.
    Supports any academic subject (biology, physics, chemistry, history, etc.).
    """
    # 1. Explicit criteria supplied by caller
    if explicit_criteria and isinstance(explicit_criteria, list):
        parsed = []
        for item in explicit_criteria:
            if isinstance(item, dict):
                crit_name = str(item.get("criterion") or item.get("name") or "").strip()
                try:
                    pts = float(item.get("max_points", item.get("points", 0)))
                except (ValueError, TypeError):
                    pts = 0.0
                if crit_name:
                    parsed.append({"criterion": crit_name, "max_points": pts})
            elif isinstance(item, str) and item.strip():
                parsed.append({"criterion": item.strip(), "max_points": 0.0})

        if parsed:
            total = sum(c["max_points"] for c in parsed)
            if total <= 0:
                base = round(10.0 / len(parsed), 1)
                rem = round(10.0 - (base * len(parsed)), 1)
                for i, c in enumerate(parsed):
                    c["max_points"] = base + (rem if i == len(parsed) - 1 else 0.0)
            return parsed

    # 2. General multi-part clause matching in question text:
    # Matches patterns like "with respect to A and B", "in terms of A, B, and C", "regarding A and B"
    q_pattern = r"(?:with respect to|in terms of|regarding|with regard to)\s+(?P<clause>[^.?\n]+)"
    m = re.search(q_pattern, question or "", re.IGNORECASE)
    if m:
        clause = m.group("clause").strip()
        parts = re.split(r",\s*(?:and\s+)?|\s+and\s+", clause)
        cleaned = [
            re.sub(r"^(the|a|an|their|its)\s+", "", p.strip(), flags=re.IGNORECASE).strip()
            for p in parts
            if p.strip()
        ]
        cleaned = [c for c in cleaned if len(c) > 2]
        if len(cleaned) >= 2:
            base = round(10.0 / len(cleaned), 1)
            rem = round(10.0 - (base * len(cleaned)), 1)
            return [
                {
                    "criterion": c.capitalize(),
                    "max_points": base + (rem if i == len(cleaned) - 1 else 0.0),
                }
                for i, c in enumerate(cleaned)
            ]

    # 3. Concept compound marker: "comparison of X and Y"
    if concept:
        c_match = re.search(r"comparison of\s+(?P<c1>.+?)\s+and\s+(?P<c2>.+)", concept, re.IGNORECASE)
        if c_match:
            c1 = c_match.group("c1").strip().capitalize()
            c2 = c_match.group("c2").strip().capitalize()
            return [
                {"criterion": c1, "max_points": 5.0},
                {"criterion": c2, "max_points": 5.0},
            ]

    return []


def format_criteria_prompt_section(criteria: list[dict[str, Any]]) -> str:
    """
    Format the criteria section for injection into GRADING_PROMPT.
    """
    if criteria:
        lines = [
            "\nREQUIRED EVALUATION CRITERIA (RUBRIC):",
            "You MUST evaluate the student's answer against each of these specific criteria independently:",
        ]
        for i, c in enumerate(criteria, 1):
            lines.append(f"{i}. Criterion: {c['criterion']} (Max points: {c['max_points']})")
        lines.append(
            "MANDATORY SCORING RULE: If an essential criterion is omitted, ignored, or not addressed in the student's answer, "
            "its awarded_points MUST be 0.0 and status MUST be 'missing'. Do NOT award full marks (10/10) to an answer that omits an explicit criterion."
        )
        return "\n".join(lines) + "\n"

    return (
        "\nREQUIRED EVALUATION CRITERIA (RUBRIC):\n"
        "Deconstruct the question into its essential required evaluation criteria (1 to 4 criteria summing to 10.0 max points). "
        "Evaluate each criterion independently. If an essential requested component is omitted, award 0.0 points for that criterion.\n"
    )


def calculate_and_validate_criteria_score(
    grading: dict[str, Any],
    student_answer: str,
    expected_criteria: list[dict[str, Any]] | None = None,
) -> tuple[float, list[dict[str, Any]]]:
    """
    Validates and calculates the final score from criteria evaluation.
    Enforces deterministic consistency so answers missing essential criteria cannot receive 10/10.
    Does not use brittle keyword filters, allowing valid paraphrases across any academic domain.
    """
    criteria = grading.get("criteria")
    student_clean = (student_answer or "").strip()

    # Empty or near-empty answer receives 0.0
    if not student_clean or len(student_clean) < 3:
        if isinstance(criteria, list) and criteria:
            sanitized = []
            for item in criteria:
                if isinstance(item, dict):
                    max_pts = float(item.get("max_points", 5.0))
                    sanitized.append({
                        "criterion": str(item.get("criterion", "Criterion")).strip(),
                        "max_points": max_pts,
                        "awarded_points": 0.0,
                        "status": "missing",
                        "evidence": "No answer provided.",
                    })
            return 0.0, sanitized
        return 0.0, []

    if isinstance(criteria, list) and criteria:
        total_max = 0.0
        total_awarded = 0.0
        sanitized_criteria = []

        for item in criteria:
            if not isinstance(item, dict):
                continue

            crit_name = str(item.get("criterion", "Criterion")).strip()
            try:
                max_pts = float(item.get("max_points", 0))
            except (ValueError, TypeError):
                max_pts = 10.0 / max(len(criteria), 1)

            try:
                awarded_pts = float(item.get("awarded_points", item.get("points", 0)))
            except (ValueError, TypeError):
                awarded_pts = 0.0

            status = str(item.get("status", "")).strip().lower()
            evidence = str(item.get("evidence", "")).strip()

            # If evidence from grader explicitly indicates omitted / missing, clamp awarded_points to 0.0
            evidence_lower = evidence.lower()
            if any(marker in evidence_lower for marker in [
                "not addressed", "not mentioned", "omitted", "missing",
                "did not address", "did not mention", "completely omitted", "absent"
            ]):
                status = "missing"
                awarded_pts = 0.0

            # Bounds check
            if max_pts > 0:
                awarded_pts = max(0.0, min(awarded_pts, max_pts))
                if awarded_pts == 0.0:
                    status = "missing"
                elif awarded_pts >= max_pts:
                    status = "fully_met"
                else:
                    status = "partially_met"

            total_max += max_pts
            total_awarded += awarded_pts

            sanitized_criteria.append({
                "criterion": crit_name,
                "max_points": max_pts,
                "awarded_points": awarded_pts,
                "status": status,
                "evidence": evidence,
            })

        if total_max > 0:
            final_score = round((total_awarded / total_max) * 10, 1)
        else:
            final_score = 0.0

        return final_score, sanitized_criteria

    # Legacy raw score fallback when AI did not return criteria
    raw_score = grading.get("score", 0)
    try:
        final_score = float(raw_score)
    except (ValueError, TypeError):
        m = re.search(r"(\d+(\.\d+)?)", str(raw_score))
        final_score = float(m.group(1)) if m else 0.0

    return max(0.0, min(10.0, final_score)), []
