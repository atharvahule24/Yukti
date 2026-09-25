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

def extract_knowledge_graph(chunks, file_path="knowledge_graph.json"):
    parser = JsonOutputParser(pydantic_object=KnowledgeGraphSchema)

    prompt = PromptTemplate(
    template="""You are an expert educational graph extractor.

Given the following educational text, extract the key learning concepts
and the meaningful relationships between them.

Organize concepts from broader concepts to more specific concepts when
the text supports such a structure. Do not invent concepts or
relationships that are not supported by the text.

Extract up to 12 meaningful nodes and their corresponding edges from
this text chunk.

Be concise. Ensure output format is strictly JSON following the schema.
{format_instructions}

Use only these relationship labels:

- requires: target concept is a prerequisite for source concept
- includes: source contains target as a sub-concept
- related_to: concepts are conceptually related
- applied_in: source is used in target/application
- defines: source defines target
- part_of: source is a component of target

For "requires", always set:
source = the concept that needs the prerequisite
target = the prerequisite concept

Example:
source: "quadratic equations"
target: "algebraic equations"
label: "requires"

For prerequisite relationships, prefer "requires".
Do not invent relationship labels.

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
        return
        
    model = ChatGroq(
        model_name="openai/gpt-oss-20b",
        temperature=0.1,
        max_tokens=1024,
        api_key=groq_api_key,
    )
    
    chain = prompt | model | parser
    
    try:
        def process_chunk(chunk):
            return chain.invoke({"text": chunk.page_content[:1200]})

        all_nodes = {}
        all_edges = []
        worker_count = min(8, max(1, len(chunks)))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = [pool.submit(process_chunk, chunk) for chunk in chunks]
            for future in as_completed(futures):
                try:
                    partial_graph = future.result()
                except Exception as exc:
                    print(f"Chunk graph extraction failed: {exc}")
                    continue
                for node in partial_graph.get("nodes", []):
                    node_id = str(node.get("id", "")).strip()
                    label = str(node.get("label", "")).strip()

                    if not node_id or not label:
                        continue

                    node["id"] = node_id
                    node["label"] = label
                    all_nodes[node_id] = node
                all_edges.extend(partial_graph.get("edges", []))

                seen_edges = set()
                unique_edges = []

                for edge in all_edges:
                    source = str(edge.get("source", "")).strip()
                    target = str(edge.get("target", "")).strip()
                    label = str(edge.get("label", "")).strip()

                    if not source or not target or not label:
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

        new_graph = {"nodes": list(all_nodes.values()), "edges": unique_edges}
                
        # Merge with existing
        merge_graph(file_path, new_graph)
        print("Successfully extracted and merged knowledge graph.")
        return new_graph
    except Exception as e:
        print(f"Error extracting knowledge graph: {e}")
        return {"nodes": [], "edges": []}

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
