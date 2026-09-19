from langchain_community.document_loaders import text_Loader,PyPDFLoader,UnstructuredWordDocumentLoader,UnstructuredPowerPointLoader 
class loader:
    def __init__(self,file_path):
        self.file_path = file_path
    def load(self):
        if self.file_path.endswith('.txt'):
            loader = text_Loader(self.file_path)
        elif self.file_path.endswith('.pdf'):
            loader = PyPDFLoader(self.file_path)
        elif self.file_path.endswith('.docx'):
            loader = UnstructuredWordDocumentLoader(self.file_path)
        elif self.file_path.endswith('.pptx'):
            loader = UnstructuredPowerPointLoader(self.file_path)
        else:
            raise ValueError("Unsupported file type")
        return loader.load()