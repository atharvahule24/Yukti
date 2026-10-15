from loaders.base_loader import BaseLoader


class FileLoader(BaseLoader):

    def _load_pdf(self):
        import pypdf
        from langchain_core.documents import Document

        documents = []
        fitz_doc = None

        def _get_fitz_doc():
            nonlocal fitz_doc
            if fitz_doc is None:
                try:
                    import fitz
                    fitz_doc = fitz.open(self.file_path)
                except Exception:
                    fitz_doc = False
            return fitz_doc if fitz_doc is not False else None

        try:
            try:
                with open(self.file_path, "rb") as f:
                    reader = pypdf.PdfReader(f)
                    for i, page in enumerate(reader.pages):
                        page_text = ""
                        try:
                            page_text = page.extract_text() or ""
                        except Exception as pypdf_err:
                            f_doc = _get_fitz_doc()
                            if f_doc and i < len(f_doc):
                                try:
                                    page_text = f_doc[i].get_text() or ""
                                except Exception as fitz_err:
                                    raise RuntimeError(
                                        f"Failed to extract text from page {i + 1}: "
                                        f"both pypdf ({pypdf_err}) and PyMuPDF ({fitz_err}) failed."
                                    ) from fitz_err
                            else:
                                raise RuntimeError(
                                    f"Failed to extract text from page {i + 1}: "
                                    f"pypdf failed ({pypdf_err}) and fallback parser is unavailable."
                                ) from pypdf_err
                        documents.append(
                            Document(
                                page_content=page_text,
                                metadata={"source": self.file_path, "page": i}
                            )
                        )
            except Exception as outer_err:
                if isinstance(outer_err, RuntimeError):
                    raise
                documents = []
                f_doc = _get_fitz_doc()
                if not f_doc:
                    raise RuntimeError(f"Failed to read PDF: {outer_err}") from outer_err
                for i, page in enumerate(f_doc):
                    try:
                        page_text = page.get_text() or ""
                    except Exception as fitz_err:
                        raise RuntimeError(
                            f"Failed to extract text from page {i + 1} with PyMuPDF: {fitz_err}"
                        ) from fitz_err
                    documents.append(
                        Document(
                            page_content=page_text,
                            metadata={"source": self.file_path, "page": i}
                        )
                    )

            total_text = "".join(doc.page_content for doc in documents).strip()
            if not total_text:
                f_doc = _get_fitz_doc()
                if f_doc:
                    documents = []
                    for i, page in enumerate(f_doc):
                        try:
                            page_text = page.get_text() or ""
                        except Exception as fitz_err:
                            raise RuntimeError(
                                f"Failed to extract text from page {i + 1} with PyMuPDF: {fitz_err}"
                            ) from fitz_err
                        documents.append(
                            Document(
                                page_content=page_text,
                                metadata={"source": self.file_path, "page": i}
                            )
                        )
                    total_text = "".join(doc.page_content for doc in documents).strip()

            if not total_text:
                raise ValueError(
                    "No readable text could be extracted from this PDF. "
                    "It may be scanned, image-only, or password-protected."
                )

            return documents
        finally:
            if fitz_doc and hasattr(fitz_doc, "close"):
                fitz_doc.close()

    def load(self):

        if self.file_path.endswith(".txt"):
            from langchain_community.document_loaders import TextLoader
            loader = TextLoader(self.file_path)
            return loader.load()

        elif self.file_path.endswith(".pdf"):
            return self._load_pdf()

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
