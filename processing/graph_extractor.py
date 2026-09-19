import os
import json
import random
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
    label: str = Field(description="The relationship between the nodes (e.g., includes, requires, relates to)")

class KnowledgeGraphSchema(BaseModel):
    nodes: List[Node] = Field(description="List of key concept nodes")
    edges: List[Edge] = Field(description="List of relationships between concept nodes")

def extract_knowledge_graph(chunks, file_path="knowledge_graph.json"):
    parser = JsonOutputParser(pydantic_object=KnowledgeGraphSchema)

    prompt = PromptTemplate(
        template="""You are an expert educational graph extractor.
Given the following text, extract a hierarchical learning route consisting of key concepts as nodes, and relationships between them as edges.
Structure the graph starting from the most general or fundamental concept (the root), and branch out to its characteristics, types, explaining different models, and then solutions or specific details. This should feel like a clear route from start to finish to learn the topic.
Extract up to 8 nodes and their corresponding edges from this text chunk.
Be concise. Ensure output format is strictly JSON following the schema.
{format_instructions}

Text:
{text}
""",
        input_variables=["text"],
        partial_variables={"format_instructions": parser.get_format_instructions()},
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
        model_kwargs={"response_format": {"type": "json_object"}}
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
                    all_nodes[node["id"]] = node
                all_edges.extend(partial_graph.get("edges", []))

        seen_edges = set()
        unique_edges = []
        for edge in all_edges:
            key = (edge.get("source"), edge.get("target"))
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(edge)

        new_graph = {"nodes": list(all_nodes.values()), "edges": unique_edges}
        
        # Give them random mastery 0-100 just for UI
        for node in new_graph.get("nodes", []):
            if "mastery" not in node:
                node["mastery"] = random.randint(0, 50)
                
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
