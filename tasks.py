import os
from datetime import datetime
from celery_app import celery
from routes.store import session_store


@celery.task(bind=True)
def process_upload(self, session_id, filepath, title, original_filename, is_youtube=False, youtube_url=None):
    try:
        import sys
        import os
        import importlib.util
        print(f"DIAG: cwd = {os.getcwd()}", flush=True)
        print(f"DIAG: sys.path = {sys.path}", flush=True)
        print(f"DIAG: /app exists = {os.path.exists('/app')}", flush=True)
        print(f"DIAG: /app/loaders exists = {os.path.exists('/app/loaders')}", flush=True)
        if os.path.exists('/app/loaders'):
            print(f"DIAG: /app/loaders files = {os.listdir('/app/loaders')}", flush=True)
        try:
            print(f"DIAG: spec loaders = {importlib.util.find_spec('loaders')}", flush=True)
        except Exception as e:
            print(f"DIAG: spec loaders Exception = {e}", flush=True)
        try:
            print(f"DIAG: spec loaders.loader_manager = {importlib.util.find_spec('loaders.loader_manager')}", flush=True)
        except Exception as e:
            print(f"DIAG: spec loaders.loader_manager Exception = {e}", flush=True)
        print("DIAG: before import loaders.loader_manager", flush=True)
        from loaders.loader_manager import LoaderManager
        print("DIAG: after import loaders.loader_manager", flush=True)

        print("DIAG: before import loaders.youtube_loader", flush=True)
        from loaders.youtube_loader import YoutubeLoader
        print("DIAG: after import loaders.youtube_loader", flush=True)

        print("DIAG: before import processing.chunker", flush=True)
        from processing.chunker import Chunker
        print("DIAG: after import processing.chunker", flush=True)

        print("DIAG: before import processing.embedder", flush=True)
        from processing.embedder import Embedder
        print("DIAG: after import processing.embedder", flush=True)

        print("DIAG: before import retrieval.vector_store", flush=True)
        from retrieval.vector_store import VectorStore
        print("DIAG: after import retrieval.vector_store", flush=True)

        if is_youtube:
            loader = YoutubeLoader(youtube_url)
            documents = loader.load()  # no args ?" URL already passed to __init__
        else:
            print("DIAG: before LoaderManager", flush=True)
            loader = LoaderManager()
            print("DIAG: after LoaderManager", flush=True)
            print("DIAG: before loader.load", flush=True)
            documents = loader.load(filepath)
            print("DIAG: after loader.load", flush=True)

        chunker = Chunker()
        chunks = chunker.split(documents)
        print("DIAG: after chunking", flush=True)

        for chunk in chunks:
            chunk.metadata["session_id"] = session_id

        print("DIAG: before Embedder", flush=True)
        embedder = Embedder()
        print("DIAG: after Embedder", flush=True)
        vector_store = VectorStore()
        vector_store.add(embedder.model, chunks)
        vector_store.save()
        print("DIAG: after vector store", flush=True)

        full_text = "\n\n".join(doc.page_content for doc in chunks)

        session_store[session_id] = {
            "id": session_id,
            "title": title,
            "original_filename": original_filename,
            "created_at": datetime.now().isoformat(),
            "chunk_count": len(chunks),
            "full_text": full_text,
            "graph": None,
            "notes": None,
            "flashcards": None,
            "quiz": None,
        }

        return {"status": "ready", "session_id": session_id, "chunk_count": len(chunks)}

    except Exception as e:
        self.update_state(state="FAILURE", meta={"error": str(e)})
        raise


@celery.task(bind=True)
def generate_graph_task(self, session_id):
    try:
        from processing.graph_extractor import extract_knowledge_graph
        from processing.chunker import Chunker
        from langchain_core.documents import Document

        session_data = session_store.get(session_id)
        if not session_data:
            raise KeyError(f"Session {session_id} not found")

        full_text = session_data.get("full_text", "")
        if not full_text:
            raise ValueError("No text found for session")

        chunks = Chunker().split([Document(page_content=full_text)])
        graph_data = extract_knowledge_graph(chunks)

        if "edges" in graph_data:
            graph_data["links"] = graph_data.pop("edges")

        session_data["graph"] = graph_data
        session_store[session_id] = session_data

        return graph_data

    except Exception as e:
        self.update_state(state="FAILURE", meta={"error": str(e)})
        raise


@celery.task(bind=True)
def generate_notes_task(self, session_id):
    try:
        from llm.generator import Generator
        from agents.prompts import NOTES_PROMPT
        from utils.json_helper import extract_json

        session_data = session_store.get(session_id)
        if not session_data:
            raise KeyError(f"Session {session_id} not found")

        full_text = session_data.get("full_text", "")[:6000]
        if not full_text:
            raise ValueError("No text found for session")

        generator = Generator(json_mode=True)
        res = generator.chain.invoke({"context": full_text, "question": NOTES_PROMPT})
        notes = extract_json(res)

        if notes:
            session_data["notes"] = notes
            session_store[session_id] = session_data

        return notes or {"points": []}

    except Exception as e:
        self.update_state(state="FAILURE", meta={"error": str(e)})
        raise


@celery.task(bind=True)
def generate_flashcards_task(self, session_id):
    try:
        from llm.generator import Generator
        from agents.prompts import FLASHCARD_GENERATION_PROMPT
        from utils.json_helper import extract_json
        from db import upsert_card_schedule, upsert_flashcard_progress

        session_data = session_store.get(session_id)
        if not session_data:
            raise KeyError(f"Session {session_id} not found")

        full_text = session_data.get("full_text", "")[:6000]
        if not full_text:
            raise ValueError("No text found for session")

        generator = Generator(json_mode=True)
        res = generator.chain.invoke({"context": full_text, "question": FLASHCARD_GENERATION_PROMPT})
        flashcards = extract_json(res)

        if flashcards:
            for i, c in enumerate(flashcards.get("cards", [])):
                c["id"] = f"card_{i}"
                c["mastery"] = 0
                c["next_review"] = datetime.now().isoformat()
                upsert_card_schedule(session_id, c["id"], c.get("front", ""), c["next_review"])

            session_data["flashcards"] = flashcards
            session_store[session_id] = session_data
            upsert_flashcard_progress(session_id, len(flashcards.get("cards", [])), 0)

        return flashcards or {"cards": []}

    except Exception as e:
        self.update_state(state="FAILURE", meta={"error": str(e)})
        raise
