import celery_app
from celery import Task
from processing.chunker import Chunker
from processing.embedder import Embedder
from retrieval.vector_store import VectorStore
from routes.store import session_store

class ProcessUploadTask(Task):
    def process_upload(self, session_id, filepath, title, original_filename, is_youtube=False):
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
                print(f"CELERY DEBUG filepath={filepath}")
                print(f"CELERY DEBUG exists_before_load={os.path.exists(filepath)}")
                print(f"CELERY DEBUG size_before_load={os.path.getsize(filepath) if os.path.exists(filepath) else 'MISSING'}")
                print(f"CELERY DEBUG uploads_dir={os.listdir('/data/uploads') if os.path.exists('/data/uploads') else 'DIRECTORY_MISSING'}")
                loader = LoaderManager()
                documents = loader.load(filepath)
            self.update_state(state="PROGRESS", meta={"stage": "Chunking text..."})
            chunker = Chunker()
            chunks = chunker.split(documents)

            for chunk in chunks:
                chunk.metadata["session_id"] = session_id

            embedder = Embedder()
            vector_store = VectorStore()
            vector_store.add(embedder.model, chunks)
            vector_store.save()

            full_text = "\n\n".join(doc.page_content for doc in chunks)

            session_store[session_id] = {
                "id": session_id,
                "title": title,
                "original_filename": original_filename,
                "content": full_text,
                "is_youtube": is_youtube,
            }

            self.update_state(state="PROGRESS", meta={"stage": "Completed!"})
            return {"status": "ready", "session_id": session_id, "chunk_count": len(chunks)}

        except Exception as e:
            raise


@celery_app.celery.task(bind=True, base=ProcessUploadTask, name="tasks.process_upload")
def process_upload(self, session_id, filepath, title, original_filename, is_youtube=False):
    return self.process_upload(session_id, filepath, title, original_filename, is_youtube)

@celery_app.celery.task(bind=True, name="tasks.generate_graph")
def generate_graph_task(self, session_id):
    from generative.graph_generator import GraphGenerator
    try:
        session = session_store.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        self.update_state(state="PROGRESS", meta={"stage": "Generating Knowledge Graph..."})
        generator = GraphGenerator()
        graph_data = generator.generate(session["content"])
        
        session["graph_data"] = graph_data
        return graph_data

    except Exception as e:
        raise


@celery_app.celery.task(bind=True, name="tasks.generate_notes")
def generate_notes_task(self, session_id):
    from generative.notes_generator import NotesGenerator
    try:
        session = session_store.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        self.update_state(state="PROGRESS", meta={"stage": "Generating Notes..."})
        generator = NotesGenerator()
        notes = generator.generate(session["content"])
        
        session["notes"] = notes
        return notes or {"points": []}

    except Exception as e:
        raise


@celery_app.celery.task(bind=True, name="tasks.generate_flashcards")
def generate_flashcards_task(self, session_id):
    from generative.flashcards_generator import FlashcardsGenerator
    try:
        session = session_store.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        self.update_state(state="PROGRESS", meta={"stage": "Generating Flashcards..."})
        generator = FlashcardsGenerator()
        flashcards = generator.generate(session["content"])
        
        session["flashcards"] = flashcards

        return flashcards or {"cards": []}

    except Exception as e:
        raise
