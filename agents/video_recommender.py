from urllib.parse import quote


def build_video_search_query(
    concept: str,
    difficulty: str = "medium",
    action: str = "review",
    misconception: str | None = None,
) -> str:
    """Build a learner-state-aware YouTube search query."""

    concept_text = (concept or "").replace("-", " ").strip()

    difficulty_terms = {
        "easy": "beginner friendly simple explanation",
        "medium": "clear detailed explanation",
        "hard": "advanced detailed explanation",
    }

    action_terms = {
        "targeted_misconception_review": "common misconceptions explained",
        "step_by_step_review": "step by step explanation",
        "example_based_review": "examples explained",
        "prerequisite_review": "basics explained",
        "review": "revision explained",
        "practice": "practice and explanation",
        "confidence_reinforcement": "quick concept review",
        "advance": "deeper explanation",
    }

    difficulty_text = difficulty_terms.get(
        difficulty,
        difficulty_terms["medium"],
    )

    action_text = action_terms.get(
        action,
        "concept explanation",
    )

    misconception_text = ""
    if misconception and misconception != "incomplete_understanding":
        misconception_text = (
            f" {misconception.replace('-', ' ')}"
        )

    return (
        f"{concept_text}{misconception_text} "
        f"{action_text} {difficulty_text}"
    )


def build_youtube_search_url(query: str) -> str:
    encoded_query = quote(query)
    return (
        "https://www.youtube.com/results"
        f"?search_query={encoded_query}"
    )


def recommend_video_search(
    concept: str,
    difficulty: str = "medium",
    action: str = "review",
    misconception: str | None = None,
) -> dict:
    query = build_video_search_query(
        concept=concept,
        difficulty=difficulty,
        action=action,
        misconception=misconception,
    )

    return {
        "type": "youtube_search",
        "query": query,
        "url": build_youtube_search_url(query),
        "concept": concept,
        "difficulty": difficulty,
        "action": action,
    }