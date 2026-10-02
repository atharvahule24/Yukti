def log_memory(label):
    try:
        import resource
        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        print(f"MEMORY: {label}: {rss_mb:.1f} MB", flush=True)
    except Exception:
        pass

log_memory("before from langchain_text_splitters import RecursiveCharacterTextSplitter")
from langchain_text_splitters import RecursiveCharacterTextSplitter
log_memory("after from langchain_text_splitters import RecursiveCharacterTextSplitter")

class Chunker:
    def __init__(self, chunk_size=800, chunk_overlap=150):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

    def split(self, documents):
        return self.splitter.split_documents(documents)
