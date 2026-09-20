CANONICAL_CONCEPTS = {
    "definition of colonialism": [
        "control over another region or people",
        "establishing settlements",
        "imposing political, economic, and cultural systems",
    ],

    "motivations for colonial expansion": [
        "economic benefits and trade opportunities",
        "access to resources and markets",
        "political influence and competition",
        "religious conversion",
        "scientific exploration and curiosity",
    ],
}


def get_canonical_concept(concept: str) -> str:
    """
    Return the stable canonical concept name.

    Concept matching is case-insensitive.
    """
    normalized = concept.strip().lower()

    for canonical_concept in CANONICAL_CONCEPTS:
        if canonical_concept.lower() == normalized:
            return canonical_concept

    return concept.strip()


def get_canonical_concepts(concept: str) -> list[str]:
    canonical_concept = get_canonical_concept(concept)

    return CANONICAL_CONCEPTS.get(
        canonical_concept,
        []
    )