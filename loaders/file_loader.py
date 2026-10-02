from loaders.base_loader import BaseLoader


class FileLoader(BaseLoader):

    def load(self):

        if self.file_path.endswith(".txt"):
            from langchain_community.document_loaders import TextLoader
            loader = TextLoader(self.file_path)

        elif self.file_path.endswith(".pdf"):
            from langchain_community.document_loaders import PyPDFLoader
            loader = PyPDFLoader(self.file_path)

        elif self.file_path.endswith(".docx"):
            from langchain_community.document_loaders import UnstructuredWordDocumentLoader
            loader = UnstructuredWordDocumentLoader(self.file_path)

        elif self.file_path.endswith(".pptx"):
            from langchain_community.document_loaders import UnstructuredPowerPointLoader
            loader = UnstructuredPowerPointLoader(self.file_path)

        else:
            raise ValueError("Unsupported file type")

        return loader.load()
