import os
from datetime import datetime, timezone
from typing import Generator
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from retrieval.vector_store import VectorStore
from processing.embedder import Embedder
from db import get_history, save_message
from agents.prompts import (
    SOCRATIC_SYSTEM,
    FEYNMAN_SYSTEM,
    SIMPLE_SYSTEM,
    EXAM_PREP_SYSTEM
)

class RagWorkflow:
    def __init__(self):
        self.groq_api_key = os.environ.get("GROQ_API_KEY")
        self.model = ChatGroq(
            model_name="openai/gpt-oss-20b",
            temperature=0.3,
            max_tokens=1024,
            api_key=self.groq_api_key,
            streaming=True
        )
        self.embedder = Embedder()
        # Ensure we use the index.faiss path structure correctly
        self.vector_store = VectorStore(index_path="vector_store")
        self.vector_store.load(self.embedder.model)

    def _get_system_prompt(self, mode: str) -> str:
        if mode == "socratic":
            return SOCRATIC_SYSTEM
        elif mode == "feynman":
            return FEYNMAN_SYSTEM
        elif mode == "simple":
            return SIMPLE_SYSTEM
        elif mode == "exam":
            return EXAM_PREP_SYSTEM
        else:
            return "You are a helpful AI study companion. Be clear, concise, and accurate."

    def run(self, message: str, session_id: str, mode: str) -> Generator[dict, None, None]:
        # Node 1: Retrieve
        # Normally session_id would be used to filter or isolate search, 
        # but FAISS doesn't easily filter by metadata in all LangChain versions unless set up.
        # Here we just search the vector store directly with metadata filtering if possible.
        try:
            # We fetch more docs and rerank/filter by session_id if needed, or assume global store for now
            # as per standard simplified setup, if filtering by session_id isn't explicitly supported in existing code.
            # We'll fetch top 5.
            print("VECTOR STORE LOADED:", self.vector_store.vector_store is not None)
            print("SESSION ID:", session_id)
            self.vector_store.load(self.embedder.model)
            docs = self.vector_store.search(message, k=5, session_id=session_id)
            print("DOCUMENTS RETRIEVED:", len(docs))
            context = "\n\n".join(doc.page_content for doc in docs)
            print("===== CONTEXT START =====", flush=True)
            print(context[:2000], flush=True)
            print("===== CONTEXT END =====", flush=True)
            print("CONTEXT PREVIEW:", context[:1000])
        except Exception:
            print("RETRIEVAL ERROR:", repr(e))
            docs = []
            context = ""

        # Node 2 & 3: Generate
        system_prompt = self._get_system_prompt(mode)
        history = get_history(session_id, limit=6) if session_id else []
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt + "\n\nContext:\n{context}"),
            *[(item["role"], item["content"]) for item in history if item["role"] in {"user", "assistant"}],
            ("user", "{message}")
        ])

        chain = prompt | self.model

        if session_id:
            save_message(session_id, "user", message, datetime.now(timezone.utc).isoformat())

        # Stream
        answer_parts = []
        for chunk in chain.stream({"context": context, "message": message}):
            if chunk.content:
                answer_parts.append(chunk.content)
                yield {"type": "token", "data": chunk.content}

        answer = "".join(answer_parts)
        if session_id and answer:
            save_message(session_id, "assistant", answer, datetime.now(timezone.utc).isoformat())

        citations = []
        for doc in docs:
            meta = doc.metadata or {}
            citations.append({
                "text": doc.page_content[:120] + ("..." if len(doc.page_content) > 120 else ""),
                "page": meta.get("page"),
                "source": meta.get("source", "document"),
            })
        yield {"type": "citations", "data": citations}
