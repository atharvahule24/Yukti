import os
from pydoc import doc
from langchain_community.vectorstores import FAISS

DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(os.path.dirname(__file__)))
DEFAULT_INDEX_PATH = os.path.join(DATA_DIR, "vector_store")

class VectorStore:

    def __init__(self, index_path=DEFAULT_INDEX_PATH):
        self.index_path = index_path
        self.vector_store = None
        self._embeddings_model = None

    def add(self, embeddings_model, documents):
        self._embeddings_model = embeddings_model
         # Create directory if missing
        os.makedirs(self.index_path, exist_ok=True)
        index_file = os.path.join(self.index_path, "index.faiss")
        if not os.path.exists(index_file):
            # First addition, create new vector store
            self.vector_store = FAISS.from_documents(documents, embeddings_model)
        else:
            # Load existing and format new documents
            self.load(embeddings_model)
            self.vector_store.add_documents(documents)

    def save(self):
        if self.vector_store is not None:
            self.vector_store.save_local(self.index_path)

    def load(self, embeddings_model):
        self._embeddings_model = embeddings_model
        index_file = os.path.join(self.index_path, "index.faiss")
        if os.path.exists(index_file):
            self.vector_store = FAISS.load_local(
                self.index_path, embeddings_model, allow_dangerous_deserialization=True
            )
        else:
            self.vector_store = None

    def _ensure_loaded(self):
        if self.vector_store is None and self._embeddings_model is not None:
            self.load(self._embeddings_model)

    def search(self, query, k=3, session_id=None):
        self._ensure_loaded()
        if self.vector_store is None:
            return []
        print("FAISS TOTAL DOCS:", self.vector_store.index.ntotal, flush=True)

        session_counts = {}
        for doc in self.vector_store.docstore._dict.values():
            sid = doc.metadata.get("session_id")
            session_counts[sid] = session_counts.get(sid, 0) + 1

        print("SESSION COUNTS:", session_counts, flush=True)
        print("LOOKING FOR SESSION:", session_id, flush=True)
        # Return LangChain Document objects
        if session_id:
            # LangChain's metadata filter is not returning the documents
            # even though they exist in the FAISS docstore.
            # Manually isolate this session first, then rank its documents
            # using the existing embedding model.

            session_docs = [
                doc
                for doc in self.vector_store.docstore._dict.values()
                if doc.metadata.get("session_id") == session_id
            ]

            print("MANUAL SESSION DOCS:", len(session_docs), flush=True)

            if not session_docs:
                return []

            query_embedding = self._embeddings_model.embed_query(query)

            scored_docs = []

            for doc in session_docs:
                doc_embedding = self._embeddings_model.embed_query(
                    doc.page_content
                )

                score = sum(
                    q * d
                    for q, d in zip(query_embedding, doc_embedding)
                )

                scored_docs.append((score, doc))

            scored_docs.sort(key=lambda item: item[0], reverse=True)

            results = [doc for _, doc in scored_docs[:k]]

            print("MANUAL RETRIEVAL RESULTS:", len(results), flush=True)

            return results
        return self.vector_store.max_marginal_relevance_search(query, k=k, fetch_k=10)
