from loaders.base_loader import BaseLoader


class FileLoader(BaseLoader):

    def load(self):
        def log_memory(label):
            try:
                import resource
                rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
                print(f"MEMORY: {label}: {rss_mb:.1f} MB", flush=True)
            except Exception:
                pass

        if self.file_path.endswith(".txt"):
            from langchain_community.document_loaders import TextLoader
            loader = TextLoader(self.file_path)
            return loader.load()

        elif self.file_path.endswith(".pdf"):
            log_memory("before creating PyPDFLoader")
            from langchain_community.document_loaders import PyPDFLoader
            loader = PyPDFLoader(self.file_path)
            log_memory("after creating PyPDFLoader")
            
            log_memory("before loader.load()")
            documents = loader.load()
            log_memory("after loader.load()")
            print(f"DIAG: PyPDFLoader loaded {len(documents)} documents", flush=True)
            return documents

        elif self.file_path.endswith(".docx"):
            from langchain_community.document_loaders import UnstructuredWordDocumentLoader
            loader = UnstructuredWordDocumentLoader(self.file_path)
            return loader.load()

        elif self.file_path.endswith(".pptx"):
            from langchain_community.document_loaders import UnstructuredPowerPointLoader
            loader = UnstructuredPowerPointLoader(self.file_path)
            return loader.load()

        else:
            raise ValueError("Unsupported file type")
