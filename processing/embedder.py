from langchain_community.embeddings.fastembed import FastEmbedEmbeddings

class Embedder:
    def __init__(self, model_name="sentence-transformers/all-MiniLM-L6-v2"):
        self.model = FastEmbedEmbeddings(
            model_name=model_name,
            batch_size=16,
            threads=1
        )
