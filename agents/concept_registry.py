import json
from pathlib import Path
from typing import Any


GRAPH_PATH = Path(__file__).resolve().parent.parent / "knowledge_graph.json"

PREREQUISITE_RELATIONS = {
    "requires",
    "depends on",
}

RELATED_RELATIONS = {
    "relates to",
    "related to",
}


def normalize_concept(concept: str) -> str:
    return " ".join((concept or "").strip().lower().split())


def load_knowledge_graph() -> dict[str, Any]:
    if not GRAPH_PATH.exists():
        return {"nodes": [], "edges": []}

    with open(GRAPH_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def build_concept_registry() -> dict[str, dict[str, Any]]:
    graph = load_knowledge_graph()

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    registry = {}

    for node in nodes:
        node_id = normalize_concept(str(node.get("id", "")))
        label = normalize_concept(str(node.get("label", "")))

        if not node_id and not label:
            continue

        concept = {
            "id": node.get("id"),
            "name": node.get("label") or node.get("id"),
            "subject": node.get("subject"),
            "mastery": node.get("mastery", 0),
            "prerequisites": [],
            "related_concepts": [],
        }

        if node_id:
            registry[node_id] = concept

        if label and label not in registry:
            registry[label] = concept

    # Build relationships from graph edges.
    for edge in edges:
        source = normalize_concept(str(edge.get("source", "")))
        target = normalize_concept(str(edge.get("target", "")))
        relation = normalize_concept(str(edge.get("label", "")))

        if not source or not target:
            continue

        source_node = registry.get(source)
        target_node = registry.get(target)

        if not source_node or not target_node:
            continue

        target_name = target_node["name"]

        if relation in PREREQUISITE_RELATIONS:
            if target_name not in source_node["prerequisites"]:
                source_node["prerequisites"].append(target_name)

        elif relation in RELATED_RELATIONS:
            if target_name not in source_node["related_concepts"]:
                source_node["related_concepts"].append(target_name)

    return registry


def get_canonical_concept(concept: str) -> str:
    return normalize_concept(concept)


def get_canonical_concepts(concept: str) -> list[str]:
    canonical = get_canonical_concept(concept)
    return [canonical] if canonical else []


def get_concept_node(
    concept: str,
    registry: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    registry = registry or build_concept_registry()
    return registry.get(normalize_concept(concept))


def get_prerequisites(
    concept: str,
    registry: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    node = get_concept_node(concept, registry)
    if not node:
        return []

    return node.get("prerequisites", [])


def get_related_concepts(
    concept: str,
    registry: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    node = get_concept_node(concept, registry)
    if not node:
        return []

    return node.get("related_concepts", [])

def get_dependent_concepts(
    concept: str,
    registry: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    registry = registry or build_concept_registry()

    target = normalize_concept(concept)

    # Resolve either an ID or a label to the canonical node.
    target_node = registry.get(target)

    if target_node:
        target_id = normalize_concept(str(target_node.get("id", "")))
        target_name = normalize_concept(str(target_node.get("name", "")))
    else:
        target_id = target
        target_name = target

    dependents = []
    seen = set()

    for node in registry.values():
        name = node.get("name", "")
        if not name:
            continue

        for prerequisite in node.get("prerequisites", []):
            prerequisite_normalized = normalize_concept(prerequisite)

            # Prerequisites are currently stored as labels.
            if prerequisite_normalized == target_name:
                if name not in seen:
                    dependents.append(name)
                    seen.add(name)
                break

            # Also support prerequisite IDs if the graph later stores them.
            if prerequisite_normalized == target_id:
                if name not in seen:
                    dependents.append(name)
                    seen.add(name)
                break

    return dependents