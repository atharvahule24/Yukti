import os
from langchain_community.vectorstores import SupabaseVectorStore
from supabase import create_client, Client

class VectorStore:

    def __init__(self, index_path=None):
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")
        self.client: Client = create_client(supabase_url, supabase_key)
        self.vector_store = None
        self._embeddings_model = None

    def add(self, embeddings_model, documents):
        self._embeddings_model = embeddings_model
        # Add documents to Supabase Vector Store
        if not self.vector_store:
            self.vector_store = SupabaseVectorStore(
                client=self.client,
                embedding=self._embeddings_model,
                table_name="documents",
                query_name="match_documents"
            )
        self.vector_store.add_documents(documents)

    def save(self):
        # Supabase is persistently hosted, no local save required.
        pass

    def load(self, embeddings_model):
        self._embeddings_model = embeddings_model
        self.vector_store = SupabaseVectorStore(
            client=self.client,
            embedding=self._embeddings_model,
            table_name="documents",
            query_name="match_documents"
        )

    def _ensure_loaded(self):
        # Since Supabase Vector Store requires the embedding model to be instantiated,
        # it is typically already created by the caller, or must be passed.
        # We assume _embeddings_model is loaded if add/load was called.
        if self.vector_store is None and self._embeddings_model is not None:
            self.load(self._embeddings_model)

    def search(self, query, k=3, session_id=None):
        self._ensure_loaded()
        if self.vector_store is None:
            # If the vector store isn't fully loaded, try to load it with a placeholder
            # But normally search() is called after load() or add().
            # If we don't have the embeddings_model, we can't perform search.
            return []

        if session_id:
            # Replicates the manual dot-product loop using Supabase JSONB filter natively.
            return self.vector_store.similarity_search(query, k=k, filter={"session_id": session_id})
        
        # Dead-code fallback MMR path from old FAISS implementation.
        return self.vector_store.max_marginal_relevance_search(query, k=k, fetch_k=10)
