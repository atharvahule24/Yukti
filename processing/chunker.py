import copy
import re

class MinimalRecursiveTextSplitter:
    """Lightweight drop-in replacement to avoid langchain_text_splitters OOM on import."""
    def __init__(self, chunk_size=800, chunk_overlap=150, separators=None):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", ". ", " ", ""]

    def _split_text(self, text, separators):
        if not text:
            return []
            
        if not separators:
            return [text[i:i+self.chunk_size] for i in range(0, len(text), max(1, self.chunk_size - self.chunk_overlap))]

        separator = separators[0]
        splits = re.split(f"({re.escape(separator)})", text) if separator else list(text)
        
        chunks = []
        current_chunk = ""
        
        for part in splits:
            if len(current_chunk) + len(part) <= self.chunk_size:
                current_chunk += part
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = current_chunk[-self.chunk_overlap:] if self.chunk_overlap > 0 else ""
                
                if len(current_chunk) + len(part) > self.chunk_size:
                    to_split = current_chunk + part
                    sub_chunks = self._split_text(to_split, separators[1:])
                    chunks.extend(sub_chunks[:-1])
                    current_chunk = sub_chunks[-1] if sub_chunks else ""
                else:
                    current_chunk += part
                    
        if current_chunk and (not chunks or current_chunk != chunks[-1]):
            chunks.append(current_chunk)
            
        return [c for c in chunks if c.strip()]

    def split_documents(self, documents):
        result = []
        for doc in documents:
            text_chunks = self._split_text(doc.page_content, self.separators)
            for text_chunk in text_chunks:
                new_doc = copy.deepcopy(doc)
                new_doc.page_content = text_chunk
                result.append(new_doc)
        return result

class Chunker:
    def __init__(self, chunk_size=800, chunk_overlap=150):
        self.splitter = MinimalRecursiveTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

    def split(self, documents):
        return self.splitter.split_documents(documents)
