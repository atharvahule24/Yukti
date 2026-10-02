from loaders.base_loader import BaseLoader


class FileLoader(BaseLoader):

    def load(self):

        if self.file_path.endswith(".txt"):
            from langchain_community.document_loaders import TextLoader
            loader = TextLoader(self.file_path)
            return loader.load()

        elif self.file_path.endswith(".pdf"):
            import pypdf
            from langchain_core.documents import Document
            
            documents = []
            with open(self.file_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                for i, page in enumerate(reader.pages):
                    text = page.extract_text()
                    documents.append(
                        Document(
                            page_content=text if text else "",
                            metadata={"source": self.file_path, "page": i}
                        )
                    )
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
