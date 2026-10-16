import os
from datetime import datetime, timezone
from typing import Generator
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, AIMessage
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

def deduplicate_and_budget_chunks(
    docs: list,
    max_chunks: int = 4,
    max_total_chars: int = 4000,
) -> list:
    """
    Filters retrieved document chunks by removing duplicates and redundant chunks,
    and limiting the total context to a measured character/chunk budget.

    Individual chunks are NEVER truncated mid-chunk to prevent loss of factual evidence.
    """
    if not docs:
        return []

    selected = []
    seen_normalized = []
    total_chars = 0

    for doc in docs:
        content = (getattr(doc, "page_content", "") or "").strip()
        if not content:
            continue

        norm = " ".join(content.split()).lower()

        # Check for duplicates or near-duplicates
        is_redundant = False
        for seen in seen_normalized:
            if norm == seen or norm in seen:
                is_redundant = True
                break
            if len(norm) > 80 and len(seen) > 80:
                if seen in norm and (len(seen) / len(norm) > 0.85):
                    is_redundant = True
                    break

        if is_redundant:
            continue

        chunk_len = len(content)

        # Budget enforcement:
        # If we already have selected chunk(s) and adding this one exceeds budget or chunk count, stop.
        # The very first selected chunk is ALWAYS kept intact even if it exceeds max_total_chars on its own.
        if selected and (total_chars + chunk_len > max_total_chars or len(selected) >= max_chunks):
            break

        selected.append(doc)
        seen_normalized.append(norm)
        total_chars += chunk_len

        if len(selected) >= max_chunks:
            break

    return selected


def prune_chat_history(
    history: list[dict],
    max_messages: int = 8,
    max_total_chars: int = 2500,
) -> list[dict]:
    """
    Prunes chat history to fit within a measured message and character budget,
    keeping conversational context while preventing prompt token explosion.
    Preserves opening question if available, plus the most recent turns.
    """
    if not history:
        return []

    # 1. Filter consecutive duplicates and invalid roles
    valid = []
    last_role = None
    last_content = None
    for item in history:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            if role == last_role and content == last_content:
                continue
            last_role = role
            last_content = content
            valid.append({"role": role, "content": content})

    if not valid:
        return []

    if len(valid) <= max_messages:
        total_len = sum(len(m["content"]) for m in valid)
        if total_len <= max_total_chars:
            return valid

    # If history exceeds message limit or char budget:
    # Anchor the first message if it's from user
    anchor = None
    remaining = valid
    remaining_budget = max_total_chars
    remaining_msg_slots = max_messages

    if valid and valid[0]["role"] == "user":
        first_len = len(valid[0]["content"])
        if first_len < max_total_chars // 2:
            anchor = valid[0]
            remaining = valid[1:]
            remaining_budget -= first_len
            remaining_msg_slots -= 1

    recent_candidates = remaining[-remaining_msg_slots:] if remaining_msg_slots > 0 else []
    selected_recent = []
    current_chars = 0
    for item in reversed(recent_candidates):
        item_len = len(item["content"])
        if selected_recent and (current_chars + item_len > remaining_budget):
            break
        selected_recent.append(item)
        current_chars += item_len

    selected_recent = list(reversed(selected_recent))

    if anchor:
        return [anchor] + selected_recent
    return selected_recent


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
            self.vector_store.load(self.embedder.model)
            raw_docs = self.vector_store.search(message, k=5, session_id=session_id)
            docs = deduplicate_and_budget_chunks(
                raw_docs,
                max_chunks=4,
                max_total_chars=4000,
            )

            context_parts = []

            for i, doc in enumerate(docs, start=1):
                metadata = doc.metadata or {}
                raw_page = metadata.get("page")

                # PDF loader pages are zero-based; display pages as one-based.
                page = (
                    raw_page + 1
                    if isinstance(raw_page, int) and not isinstance(raw_page, bool)
                    else "Unknown"
                )

                context_parts.append(
                    f"[SOURCE {i} | PDF PAGE {page}]\n"
                    f"{doc.page_content}"
                )

            context = "\n\n".join(context_parts)
        except Exception as e:
            print("RETRIEVAL ERROR:", repr(e))
            docs = []
            context = ""

        # Node 2 & 3: Generate
        system_prompt = self._get_system_prompt(mode)

        history = get_history(session_id, limit=16) if session_id else []
        pruned_history = prune_chat_history(
            history,
            max_messages=8,
            max_total_chars=2500,
        )

        rag_system_prompt = system_prompt + """

STRICT RAG GROUNDING RULES:

1. Answer using only the retrieved study material below.
2. Do not introduce facts, examples, species names, definitions,
   or explanations that are not supported by the retrieved material.
3. If the material does not support a claim, do not guess.
   Clearly state that the retrieved material does not provide
   enough information.
4. Preserve the terminology used in the source.
   Do not replace textbook examples with your own examples.
5. Every factual claim about the uploaded document must be
   supported by a relevant source marker such as [SOURCE 1].
6. Use the PDF page number shown in the source marker when
   referring to a page. Do not invent page references.
7. Distinguish explicitly between information stated in the
   source and information that cannot be verified from it.

8. Treat each [SOURCE n | PDF PAGE p] header as authoritative.
   SOURCE n identifies the retrieved chunk numbered n in the context.
9. Never invent, renumber, or guess a source ID or PDF page.
10. Cite a claim only when that specific retrieved chunk supports it.
11. If no retrieved chunk supports a claim, say the provided
    retrieved material does not establish it.
12. Do not cite a source merely because it is present in context;
    verify that its text supports the claim.


Retrieved study material:
{context}
"""

        history_messages = [
            HumanMessage(content=item["content"])
            if item["role"] == "user"
            else AIMessage(content=item["content"])
            for item in pruned_history
        ]

        prompt = ChatPromptTemplate.from_messages([
            ("system", rag_system_prompt),
            *history_messages,
            ("user", "{message}")
        ])

        chain = prompt | self.model

        if session_id:
            save_message(
                session_id,
                "user",
                message,
                datetime.now(timezone.utc).isoformat()
            )

        print("===== LLM GENERATION START =====", flush=True)

        response = chain.invoke({
            "context": context,
            "message": message
        })

        print("LLM RESPONSE TYPE:", type(response), flush=True)
        print("LLM RESPONSE CONTENT:", repr(response.content), flush=True)

        answer = response.content or ""

        import re

        # Flexible regex matching [SOURCE n] or [SOURCE n | PDF PAGE p] across brackets and parentheses
        source_marker_pattern = re.compile(
            r"[\[(【]\s*SOURCE\s+(\d+)(?:\s*[\|,]\s*(?:PDF\s+)?PAGE\s+\d+)?\s*[\])】]",
            flags=re.IGNORECASE,
        )

        valid_cited_source_ids = set()

        def normalize_and_validate_marker(match):
            try:
                source_id = int(match.group(1))
            except (ValueError, TypeError):
                return ""

            # Validate against actual retrieved documents (1 <= source_id <= len(docs))
            if 1 <= source_id <= len(docs):
                valid_cited_source_ids.add(source_id)
                # Derive PDF page number strictly from document metadata; never trust LLM output
                raw_page = (docs[source_id - 1].metadata or {}).get("page")
                page = (
                    raw_page + 1
                    if isinstance(raw_page, int) and not isinstance(raw_page, bool)
                    else "Unknown"
                )
                return f"[SOURCE {source_id} | PDF PAGE {page}]"

            # Reject invalid or out-of-range source IDs: strip from answer text
            return ""

        answer = source_marker_pattern.sub(normalize_and_validate_marker, answer).strip()

        if answer:
            yield {"type": "token", "data": answer}

        if session_id and answer:
            save_message(
                session_id,
                "assistant",
                answer,
                datetime.now(timezone.utc).isoformat(),
            )

        citations = []

        for source_id in sorted(valid_cited_source_ids):
            doc = docs[source_id - 1]
            meta = doc.metadata or {}
            raw_page = meta.get("page")

            citations.append({
                "source_id": source_id,
                "text": doc.page_content[:120] + (
                    "..." if len(doc.page_content) > 120 else ""
                ),
                "page": (
                    raw_page + 1
                    if isinstance(raw_page, int)
                    and not isinstance(raw_page, bool)
                    else None
                ),
                "source": meta.get("source", "document"),
            })

        yield {"type": "citations", "data": citations}
