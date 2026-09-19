from langchain_community.document_loaders import (
    TextLoader,
    PyPDFLoader,
    UnstructuredWordDocumentLoader,
    UnstructuredPowerPointLoader
)

from loaders.base_loader import BaseLoader


class FileLoader(BaseLoader):

    def load(self):

        if self.file_path.endswith(".txt"):
            loader = TextLoader(self.file_path)

        elif self.file_path.endswith(".pdf"):
            loader = PyPDFLoader(self.file_path)

        elif self.file_path.endswith(".docx"):
            loader = UnstructuredWordDocumentLoader(self.file_path)

        elif self.file_path.endswith(".pptx"):
            loader = UnstructuredPowerPointLoader(self.file_path)

        else:
            raise ValueError("Unsupported file type")

        return loader.load()
