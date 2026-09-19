CANONICAL_CONCEPTS = {
    "definition of colonialism": [
        "control over another region or people",
        "establishing settlements",
        "imposing political, economic, and cultural systems",
    ]
}


def get_canonical_concepts(concept: str) -> list[str]:
    return CANONICAL_CONCEPTS.get(
        concept.strip().lower(),
        []
    )