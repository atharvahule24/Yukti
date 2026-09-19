from typing import TypedDict, List
from langgraph.graph import StateGraph, START, END
from langchain_core.documents import Document

from processing.embedder import Embedder
from retrieval.vector_store import VectorStore
from llm.generator import Generator

# Define State
class AgentState(TypedDict):
    query: str
    context: List[Document]
    answer: str
    

# Define Nodes
def retrieve_node(state: AgentState):
    query = state["query"]
    # Instantiate necessary classes. In a perfect setup these would be global singletons,
    # but we follow the original design pattern of instantiating on demand.
    embedder = Embedder()
    vector_store = VectorStore()
    vector_store.load(embedder.model)
    
    docs = vector_store.search(query, k=3)
    return {"context": docs}

def generate_node(state: AgentState):
    query = state["query"]
    context = state["context"]
    
    generator = Generator()
    answer = generator.generate(context, query)
    return {"answer": answer}

# Compile Graph
def build_graph():
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("generate", generate_node)
    
    # Add edges
    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", END)
    
    # Compile
    app = workflow.compile()
    return app

# Expose compiled app
rag_graph = build_graph()
