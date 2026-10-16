import os
import uuid
import celery_app
import tempfile
from celery import Task
from processing.chunker import Chunker
from processing.embedder import Embedder
from retrieval.vector_store import VectorStore
from routes.store import session_store
from db import supabase


class ProcessUploadTask(Task):
    def process_upload(self, session_id, filepath, title, original_filename, is_youtube=False):
        local_tmp = None
        try:
            from loaders.loader_manager import LoaderManager
            from loaders.youtube_loader import YoutubeLoader
            
            self.update_state(state="PROGRESS", meta={"stage": "Loading File..."})
            if is_youtube:
                loader = YoutubeLoader()
                documents = loader.load(filepath)
            else:
                import socket
                print(f"CELERY DEBUG hostname={socket.gethostname()}")
                print(f"CELERY DEBUG storage_path={filepath}")
                
                # filepath is actually the storage_path in Supabase now
                storage_path = filepath



                # Inside process_upload(), replace the hardcoded /tmp path:
                local_tmp = os.path.join(
                    tempfile.gettempdir(),
                    f"{uuid.uuid4()}.pdf"
                )

                
                # Download from Supabase Storage
                file_bytes = supabase.storage.from_("uploads").download(storage_path)
                with open(local_tmp, "wb") as f:
                    f.write(file_bytes)
                
                print(f"CELERY DEBUG local_tmp={local_tmp}")
                print(f"CELERY DEBUG exists_before_load={os.path.exists(local_tmp)}")
                print(f"CELERY DEBUG size_before_load={os.path.getsize(local_tmp) if os.path.exists(local_tmp) else 'MISSING'}")
                
                loader = LoaderManager()
                documents = loader.load(local_tmp)
                
            self.update_state(state="PROGRESS", meta={"stage": "Chunking text..."})
            
            # Create Embedder before we start allocating chunks, but after documents are loaded.
            embedder = Embedder()
            vector_store = VectorStore()
            chunker = Chunker()
            
            full_text_parts = []
            chunk_count = 0
            
            # O(1) pop strategy: reverse the list so pop() removes from the end (original front)
            documents.reverse()
            
            while documents:
                doc = documents.pop()
                
                # Chunk only a single document at a time
                doc_chunks = chunker.split([doc])
                
                if not doc_chunks:
                    del doc
                    continue
                    

                for chunk in doc_chunks:
                    # PostgreSQL text columns cannot store NULL characters.
                    chunk.page_content = chunk.page_content.replace("\x00", "")
                    chunk.metadata["session_id"] = session_id
                    full_text_parts.append(chunk.page_content)

                chunk_count += len(doc_chunks)
                vector_store.add(embedder.model, doc_chunks)

                
                # Explicitly release temporary objects; Python refcount instantly reclaims them
                del doc
                del doc_chunks
                
            # EXPLICIT MEMORY RELEASE
            del loader
            del chunker
            del embedder
            del vector_store
            import gc
            gc.collect()

            if chunk_count == 0:
                raise ValueError("No readable text could be extracted from this document.")

            full_text = "\n\n".join(full_text_parts)
            del full_text_parts

            existing_session = session_store.get(session_id) or {}
            existing_session.update({
                "id": session_id,
                "title": title,
                "original_filename": original_filename,
                "content": full_text,
                "full_text": full_text,
                "is_youtube": is_youtube,
                "status": "ready",
                "chunk_count": chunk_count,
            })
            session_store[session_id] = existing_session

            self.update_state(state="PROGRESS", meta={"stage": "Completed!"})
            return {"status": "ready", "session_id": session_id, "chunk_count": chunk_count}

        except Exception as e:
            try:
                failed_session = session_store.get(session_id) or {}
                failed_session.update({
                    "id": session_id,
                    "title": title,
                    "original_filename": original_filename,
                    "status": "failed",
                    "error": str(e),
                    "chunk_count": 0,
                })
                session_store[session_id] = failed_session
            except Exception as update_err:
                print(f"Failed to record session failure state: {update_err}")
            raise
        finally:
            if local_tmp and os.path.exists(local_tmp):
                try:
                    os.remove(local_tmp)
                except Exception as e:
                    print(f"Failed to remove temporary file {local_tmp}: {e}")
            import gc
            gc.collect()

@celery_app.celery.task(bind=True, base=ProcessUploadTask, name="tasks.process_upload")
def process_upload(self, session_id, filepath, title, original_filename, is_youtube=False):
    return self.process_upload(session_id, filepath, title, original_filename, is_youtube)

@celery_app.celery.task(bind=True, name="tasks.generate_graph")
def generate_graph_task(self, session_id, force=False):
    try:
        from processing.graph_extractor import extract_knowledge_graph

        session = session_store.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        # Helper to detect whether graph data represents a meaningful, valid graph
        def _is_valid_graph(g):
            if not g or not isinstance(g, dict):
                return False
            nodes = g.get("nodes", [])
            links = g.get("links") or g.get("edges") or []
            # Valid if 2+ concepts exist (even isolated), or at least 1 concept with links
            return len(nodes) > 1 or (len(nodes) == 1 and len(links) > 0)

        existing_graph = session.get("graph")
        has_valid_graph = _is_valid_graph(existing_graph)
        if not force and has_valid_graph:
            return existing_graph

        self.update_state(state="PROGRESS", meta={"stage": "Generating Knowledge Graph..."})
        full_text = session.get("full_text", "")
        if not full_text:
            raise ValueError("No text found for session")

        if len(full_text) > 6000:
            mid = len(full_text) // 2
            sampled_text = f"{full_text[:2000]}\n\n{full_text[mid - 1000:mid + 1000]}\n\n{full_text[-2000:]}"
        else:
            sampled_text = full_text

        try:
            # Single logical LLM pass directly on sampled context
            graph_data = extract_knowledge_graph(sampled_text) or {"nodes": [], "edges": [], "links": []}
        except Exception as llm_err:
            err_str = str(llm_err)
            if "429" in err_str or "rate_limit" in err_str.lower() or "tpd" in err_str.lower():
                import re
                m = re.search(r"Please try again in ([^,;]+?s\b)", err_str)
                cooldown_hint = f" Please try again in {m.group(1)}." if m else " Please wait a few minutes before retrying."
                raise RuntimeError(
                    f"Groq API rate limit reached (daily token limit exceeded).{cooldown_hint}"
                ) from llm_err
            raise

        if "edges" in graph_data and "links" not in graph_data:
            graph_data["links"] = graph_data.pop("edges")
        elif "links" in graph_data and "edges" not in graph_data:
            graph_data["edges"] = graph_data.get("links", [])

        # Prevent overwriting an existing valid graph with a failed or empty extraction
        if not _is_valid_graph(graph_data):
            if has_valid_graph:
                print(f"Extraction returned invalid graph; preserving existing valid graph for session {session_id}.")
                return existing_graph
            raise ValueError("Failed to extract a valid knowledge graph from document text: no concepts or links found.")
            
        session["graph"] = graph_data
        session_store[session_id] = session
        return graph_data

    except Exception as e:
        raise
    finally:
        import gc
        gc.collect()


def normalize_and_validate_notes(raw_notes):
    """
    Normalizes extracted notes from various possible LLM response shapes
    ({"points": [...]}, {"notes": [...]}, {"key_concepts": [...]}, {"cards": [...]}, or raw list)
    into standard {"points": [ {"bullet": ..., "explanation": ..., "example": ..., "importance": ...} ]}.
    Raises ValueError if no valid note items are found.
    """
    candidates = None
    if isinstance(raw_notes, list):
        candidates = raw_notes
    elif isinstance(raw_notes, dict):
        for key in ("points", "notes", "key_concepts", "cards", "concepts", "items"):
            val = raw_notes.get(key)
            if isinstance(val, list):
                candidates = val
                break
        if candidates is None and "bullet" in raw_notes and "explanation" in raw_notes:
            candidates = [raw_notes]

    if not candidates or not isinstance(candidates, list):
        raise ValueError("Failed to extract valid notes from LLM response: missing or invalid notes array.")

    valid_points = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        bullet = str(item.get("bullet") or item.get("title") or item.get("concept") or "").strip()
        explanation = str(item.get("explanation") or item.get("description") or item.get("content") or "").strip()
        example = str(item.get("example") or "").strip()
        importance = str(item.get("importance") or "medium").strip().lower()
        if importance not in ("high", "medium", "low"):
            importance = "medium"

        if bullet and explanation:
            valid_points.append({
                "bullet": bullet,
                "explanation": explanation,
                "example": example,
                "importance": importance,
            })

    if not valid_points:
        raise ValueError("Failed to extract valid notes from LLM response: no valid note points found.")

    return {"points": valid_points}


@celery_app.celery.task(bind=True, name="tasks.generate_notes")
def generate_notes_task(self, session_id):
    try:
        from llm.generator import Generator
        from agents.prompts import NOTES_PROMPT
        from utils.json_helper import extract_json

        session = session_store.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        existing_notes = session.get("notes")
        has_valid_notes = isinstance(existing_notes, dict) and bool(existing_notes.get("points"))

        self.update_state(state="PROGRESS", meta={"stage": "Generating Notes..."})
        full_text = session.get("full_text", "")[:6000]
        if not full_text:
            raise ValueError("No text found for session")

        try:
            generator = Generator(json_mode=True)
            res = generator.chain.invoke({"context": full_text, "question": NOTES_PROMPT})
        except Exception as llm_err:
            err_str = str(llm_err)
            if "429" in err_str or "rate_limit" in err_str.lower() or "tpd" in err_str.lower():
                import re
                m = re.search(r"Please try again in ([^,;]+?s\b)", err_str)
                cooldown_hint = f" Please try again in {m.group(1)}." if m else " Please wait a few minutes before retrying."
                raise RuntimeError(
                    f"Groq API rate limit reached (daily token limit exceeded).{cooldown_hint}"
                ) from llm_err
            raise

        raw_notes = extract_json(res)
        if not raw_notes:
            if has_valid_notes:
                print(f"Extraction returned invalid notes; preserving existing valid notes for session {session_id}.")
                return existing_notes
            raise ValueError("Failed to extract valid notes from LLM response: response was not valid JSON.")

        try:
            normalized_notes = normalize_and_validate_notes(raw_notes)
        except ValueError:
            if has_valid_notes:
                print(f"Extraction returned invalid notes; preserving existing valid notes for session {session_id}.")
                return existing_notes
            raise

        session["notes"] = normalized_notes
        session_store[session_id] = session
        return normalized_notes

    except Exception as e:
        raise
    finally:
        import gc
        gc.collect()


def normalize_and_validate_flashcards(raw_flashcards):
    """
    Normalizes extracted flashcards from various possible LLM response shapes
    ({"cards": [...]}, {"flashcards": [...]}, {"deck": [...]}, or raw list)
    into standard {"cards": [ {"id": ..., "front": ..., "back": ..., "explanation": ..., "hint": ...} ]}.
    Raises ValueError if no valid cards are found.
    """
    candidates = None
    if isinstance(raw_flashcards, list):
        candidates = raw_flashcards
    elif isinstance(raw_flashcards, dict):
        for key in ("cards", "flashcards", "deck", "items"):
            val = raw_flashcards.get(key)
            if isinstance(val, list):
                candidates = val
                break

    if not candidates or not isinstance(candidates, list):
        raise ValueError("Failed to extract valid flashcards from LLM response: missing or invalid cards array.")

    valid_cards = []
    for i, item in enumerate(candidates):
        if not isinstance(item, dict):
            continue
        front = str(item.get("front") or item.get("question") or "").strip()
        back = str(item.get("back") or item.get("answer") or "").strip()
        explanation = str(item.get("explanation") or "").strip()
        hint = str(item.get("hint") or "").strip()

        if front and back:
            valid_cards.append({
                "id": f"card_{i}",
                "front": front,
                "back": back,
                "explanation": explanation,
                "hint": hint,
            })

    if not valid_cards:
        raise ValueError("Failed to extract valid flashcards from LLM response: no valid cards found.")

    return {"cards": valid_cards}


@celery_app.celery.task(bind=True, name="tasks.generate_flashcards")
def generate_flashcards_task(self, session_id):
    try:
        from llm.generator import Generator
        from agents.prompts import FLASHCARD_GENERATION_PROMPT
        from utils.json_helper import extract_json
        from db import upsert_card_schedule, upsert_flashcard_progress
        from datetime import datetime

        session = session_store.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        existing_flashcards = session.get("flashcards")
        has_valid_flashcards = isinstance(existing_flashcards, dict) and bool(existing_flashcards.get("cards"))

        self.update_state(state="PROGRESS", meta={"stage": "Generating Flashcards..."})
        full_text = session.get("full_text", "")[:6000]
        if not full_text:
            raise ValueError("No text found for session")

        try:
            generator = Generator(json_mode=True)
            res = generator.chain.invoke({"context": full_text, "question": FLASHCARD_GENERATION_PROMPT})
        except Exception as llm_err:
            err_str = str(llm_err)
            if "429" in err_str or "rate_limit" in err_str.lower() or "tpd" in err_str.lower():
                import re
                m = re.search(r"Please try again in ([^,;]+?s\b)", err_str)
                cooldown_hint = f" Please try again in {m.group(1)}." if m else " Please wait a few minutes before retrying."
                raise RuntimeError(
                    f"Groq API rate limit reached (daily token limit exceeded).{cooldown_hint}"
                ) from llm_err
            if has_valid_flashcards:
                print(f"Extraction raised error; preserving existing valid cards for session {session_id}.")
                return existing_flashcards
            raise

        raw_flashcards = extract_json(res)
        if not raw_flashcards:
            if has_valid_flashcards:
                print(f"Extraction returned invalid flashcards; preserving existing valid cards for session {session_id}.")
                return existing_flashcards
            raise ValueError("Failed to extract valid flashcards from LLM response: response was not valid JSON.")

        try:
            normalized_flashcards = normalize_and_validate_flashcards(raw_flashcards)
        except ValueError:
            if has_valid_flashcards:
                print(f"Extraction returned invalid flashcards; preserving existing valid cards for session {session_id}.")
                return existing_flashcards
            raise

        cards_list = normalized_flashcards["cards"]
        for c in cards_list:
            upsert_card_schedule(
                session_id=session_id,
                card_id=c["id"],
                front=c.get("front", ""),
                next_review=datetime.utcnow().isoformat()
            )
        upsert_flashcard_progress(session_id, len(cards_list), 0)
        
        session["flashcards"] = normalized_flashcards
        session_store[session_id] = session

        return normalized_flashcards

    except Exception as e:
        raise
    finally:
        import gc
        gc.collect()
