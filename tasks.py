import os
import uuid
import celery_app
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
                local_tmp = f"/tmp/{uuid.uuid4()}.pdf"
                
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
            chunker = Chunker()
            chunks = chunker.split(documents)

            for chunk in chunks:
                chunk.metadata["session_id"] = session_id

            chunk_count = len(chunks)
            
            # EXPLICIT MEMORY RELEASE: Destroy raw document data and heavy objects
            del documents
            del loader
            del chunker
            import gc
            gc.collect()

            embedder = Embedder()
            vector_store = VectorStore()
            batch_size = 50
            
            full_text_parts = []
            
            while chunks:
                batch = chunks[:batch_size]
                del chunks[:batch_size]  # Pop chunks out of main list to free RAM
                
                for doc in batch:
                    full_text_parts.append(doc.page_content)
                    
                vector_store.add(embedder.model, batch)
                
                # FAISS vector_store.save() removed, Supabase persists automatically
                del batch
                gc.collect()

            full_text = "\n\n".join(full_text_parts)
            del full_text_parts

            session_store[session_id] = {
                "id": session_id,
                "title": title,
                "original_filename": original_filename,
                "content": full_text,
                "full_text": full_text,
                "is_youtube": is_youtube,
            }

            self.update_state(state="PROGRESS", meta={"stage": "Completed!"})
            return {"status": "ready", "session_id": session_id, "chunk_count": chunk_count}

        except Exception as e:
            raise
        finally:
            if local_tmp and os.path.exists(local_tmp):
                try:
                    os.remove(local_tmp)
                except Exception as e:
                    print(f"Failed to remove temporary file {local_tmp}: {e}")

@celery_app.celery.task(bind=True, base=ProcessUploadTask, name="tasks.process_upload")
def process_upload(self, session_id, filepath, title, original_filename, is_youtube=False):
    return self.process_upload(session_id, filepath, title, original_filename, is_youtube)

@celery_app.celery.task(bind=True, name="tasks.generate_graph")
def generate_graph_task(self, session_id):
    try:
        from processing.graph_extractor import extract_knowledge_graph
        from processing.chunker import Chunker
        from langchain_core.documents import Document

        session = session_store.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        self.update_state(state="PROGRESS", meta={"stage": "Generating Knowledge Graph..."})
        full_text = session.get("full_text", "")
        if not full_text:
            raise ValueError("No text found for session")

        chunks = Chunker().split([Document(page_content=full_text)])
        graph_data = extract_knowledge_graph(chunks)

        if "edges" in graph_data:
            graph_data["links"] = graph_data.pop("edges")
            
        session["graph"] = graph_data
        session_store[session_id] = session
        return graph_data

    except Exception as e:
        raise


@celery_app.celery.task(bind=True, name="tasks.generate_notes")
def generate_notes_task(self, session_id):
    try:
        from llm.generator import Generator
        from agents.prompts import NOTES_PROMPT
        from utils.json_helper import extract_json

        session = session_store.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        self.update_state(state="PROGRESS", meta={"stage": "Generating Notes..."})
        full_text = session.get("full_text", "")[:6000]
        if not full_text:
            raise ValueError("No text found for session")

        generator = Generator(json_mode=True)
        res = generator.chain.invoke({"context": full_text, "question": NOTES_PROMPT})
        notes = extract_json(res)
        
        if notes:
            session["notes"] = notes
            session_store[session_id] = session
            
        return notes or {"points": []}

    except Exception as e:
        raise


@celery_app.celery.task(bind=True, name="tasks.generate_flashcards")
def generate_flashcards_task(self, session_id):
    try:
        from llm.generator import Generator
        from agents.prompts import FLASHCARD_GENERATION_PROMPT
        from utils.json_helper import extract_json
        from db import upsert_card_schedule, upsert_flashcard_progress

        session = session_store.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        self.update_state(state="PROGRESS", meta={"stage": "Generating Flashcards..."})
        full_text = session.get("full_text", "")[:6000]
        if not full_text:
            raise ValueError("No text found for session")

        generator = Generator(json_mode=True)
        res = generator.chain.invoke({"context": full_text, "question": FLASHCARD_GENERATION_PROMPT})
        flashcards = extract_json(res)
        
        if flashcards:
            for i, c in enumerate(flashcards.get("cards", [])):
                upsert_card_schedule(
                    session_id=session_id,
                    card_id=f"card_{i}",
                    card_data=c
                )
            upsert_flashcard_progress(session_id, len(flashcards.get("cards", [])), 0, 0)
            
            session["flashcards"] = flashcards
            session_store[session_id] = session

        return flashcards or {"cards": []}

    except Exception as e:
        raise
