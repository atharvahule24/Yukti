import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import List

class Node(BaseModel):
    id: str = Field(description="A unique lowercase snake_case identifier for the node")
    label: str = Field(description="The display name of the concept")
    subject: str = Field(description="The general subject area (e.g., Physics, Biology, Strategy)")

class Edge(BaseModel):
    source: str = Field(description="The id of the source node")
    target: str = Field(description="The id of the target node")
    label: str = Field(
        description=(
            "Relationship type. Use exactly one of: "
            "requires, includes, related_to, applied_in, "
            "defines, part_of"
        )
    )

class KnowledgeGraphSchema(BaseModel):
    nodes: List[Node] = Field(description="List of key concept nodes")
    edges: List[Edge] = Field(description="List of relationships between concept nodes")

def extract_knowledge_graph(content, file_path="knowledge_graph.json"):
    """
    Extract educational knowledge graph in a single logical LLM pass.
    Accepts a list of document chunks or a raw text string.
    Produces a coherent hierarchical mind map with clean node/edge validation.
    """
    parser = JsonOutputParser(pydantic_object=KnowledgeGraphSchema)

    prompt = PromptTemplate(
        template="""You are an expert educational knowledge graph extractor.

Given the following educational text, extract a coherent, hierarchical mind map of key learning concepts
and the meaningful relationships between them in a single comprehensive graph.

ORGANIZATION & HIERARCHY RULES:
1. Identify exactly 1 central root concept representing the overarching subject of the text.
2. Identify 3 to 6 major sub-topics branching directly from the root concept (using "includes" or "defines").
3. Connect sub-topics to specific details, prerequisites ("requires"), or applications ("applied_in", "part_of").
4. Extract between 8 and 18 meaningful concept nodes in total with their connecting edges.
5. Do NOT invent concepts or relationships that are not directly supported by the text.

Be concise. Output format must be strictly valid JSON following the schema.
{format_instructions}

Use ONLY these relationship labels:
- includes: source concept contains target as a major sub-topic/branch
- defines: source concept defines or introduces target concept
- requires: target concept is a prerequisite needed to understand source concept
- related_to: concepts are conceptually related
- applied_in: source concept is applied or used in target context
- part_of: source concept is a component or part of target

For "requires", always set:
source = the concept that needs the prerequisite
target = the prerequisite concept

Node IDs must be unique lowercase snake_case identifiers (e.g. "photosynthesis", "light_reactions").
Node labels must be clean display names (e.g. "Photosynthesis", "Light Reactions").
Do not create self-referential edges (where source == target).

Text:
{text}
""",
        input_variables=["text"],
        partial_variables={
            "format_instructions": parser.get_format_instructions()
        },
    )

    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        print("Warning: GROQ_API_KEY not found. Skipping graph extraction.")
        return {"nodes": [], "edges": [], "links": []}

    # Normalize input text
    if isinstance(content, str):
        full_text = content
    elif isinstance(content, list):
        text_parts = []
        for item in content:
            if hasattr(item, "page_content"):
                text_parts.append(item.page_content)
            elif isinstance(item, dict) and "page_content" in item:
                text_parts.append(item["page_content"])
            else:
                text_parts.append(str(item))
        full_text = "\n\n".join(text_parts)
    else:
        full_text = str(content)

    if not full_text.strip():
        return {"nodes": [], "edges": [], "links": []}

    # Bounded text window for single pass (up to 5000 characters)
    if len(full_text) > 5000:
        mid = len(full_text) // 2
        sampled_text = f"{full_text[:2000]}\n\n{full_text[mid - 500:mid + 500]}\n\n{full_text[-2000:]}"
    else:
        sampled_text = full_text

    model = ChatGroq(
        model_name="openai/gpt-oss-20b",
        temperature=0.1,
        max_tokens=4096,
        api_key=groq_api_key,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    chain = prompt | model | parser

    try:
        # Single logical LLM pass
        raw_graph = chain.invoke({"text": sampled_text}) or {}

        all_nodes = {}
        for node in raw_graph.get("nodes", []):
            raw_id = str(node.get("id", "")).strip().lower().replace(" ", "_")
            label = str(node.get("label", "")).strip()
            subject = str(node.get("subject", "General")).strip() or "General"

            if not raw_id or not label:
                continue

            all_nodes[raw_id] = {
                "id": raw_id,
                "label": label,
                "subject": subject
            }

        allowed_labels = {"requires", "includes", "related_to", "applied_in", "defines", "part_of"}
        seen_edges = set()
        unique_edges = []

        for edge in raw_graph.get("edges", []):
            source = str(edge.get("source", "")).strip().lower().replace(" ", "_")
            target = str(edge.get("target", "")).strip().lower().replace(" ", "_")
            label = str(edge.get("label", "related_to")).strip().lower()

            if label not in allowed_labels:
                label = "related_to"

            if not source or not target or source == target:
                continue

            if source not in all_nodes or target not in all_nodes:
                continue

            key = (source, target, label)
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append({
                    "source": source,
                    "target": target,
                    "label": label,
                })

        new_graph = {
            "nodes": list(all_nodes.values()),
            "edges": unique_edges,
            "links": unique_edges
        }

        # Safe merge with existing registry file
        if file_path:
            try:
                merge_graph(file_path, new_graph)
            except Exception as me:
                print(f"Non-critical: could not merge knowledge graph to file: {me}")

        print(f"Successfully extracted single-pass knowledge graph: {len(all_nodes)} nodes, {len(unique_edges)} edges.")
        return new_graph

    except Exception as e:
        print(f"Error in single-pass knowledge graph extraction: {e}")
        raise

def merge_graph(file_path, new_graph):
    # Load existing
    existing = {"nodes": [], "edges": []}
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
            
    # Merge nodes
    existing_node_ids = {n["id"] for n in existing.get("nodes", [])}
    for n in new_graph.get("nodes", []):
        if n["id"] not in existing_node_ids:
            existing.setdefault("nodes", []).append(n)
            existing_node_ids.add(n["id"])
            
    # Merge edges
    existing_edges = {(e["source"], e["target"]) for e in existing.get("edges", [])}
    for e in new_graph.get("edges", []):
        if (e["source"], e["target"]) not in existing_edges:
            existing.setdefault("edges", []).append(e)
            existing_edges.add((e["source"], e["target"]))
            
    # Save
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=4)
