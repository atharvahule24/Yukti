from langchain_huggingface import HuggingFaceEmbeddings

class Embedder:
    def __init__(self, model_name="all-MiniLM-L6-v2"):
        self.model = HuggingFaceEmbeddings(model_name=model_name)

    def embed_documents(self, texts):
        # We might not need this explicitly since FAISS uses the model object directly, 
        # but kept for backward compatibility if needed:
        return self.model.embed_documents(texts)
