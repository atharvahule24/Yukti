import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import fitz

from app import app
from loaders.file_loader import FileLoader


class TestPdfProcessingResilience(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pdf_path = os.path.join(self.temp_dir.name, "test_sample.pdf")

        # Create a sample PDF with 2 pages of known text
        doc = fitz.open()
        page1 = doc.new_page()
        page1.insert_text((50, 72), "Yukti Page 1 Content")
        page2 = doc.new_page()
        page2.insert_text((50, 72), "Yukti Page 2 Content")
        doc.save(self.pdf_path)
        doc.close()

        # Create a blank PDF
        self.blank_pdf_path = os.path.join(self.temp_dir.name, "blank.pdf")
        blank_doc = fitz.open()
        blank_doc.new_page()
        blank_doc.save(self.blank_pdf_path)
        blank_doc.close()

        self.client = app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_pdf_extraction_pypdf(self):
        """Verifies normal PDF extraction returns Document objects with content and page metadata."""
        loader = FileLoader(self.pdf_path)
        docs = loader.load()
        self.assertEqual(len(docs), 2)
        self.assertIn("Yukti Page 1 Content", docs[0].page_content)
        self.assertEqual(docs[0].metadata["page"], 0)
        self.assertIn("Yukti Page 2 Content", docs[1].page_content)
        self.assertEqual(docs[1].metadata["page"], 1)

    def test_pypdf_page_unbound_local_error_fallback_to_fitz(self):
        """
        Simulates the exact production UnboundLocalError in pypdf extraction
        and verifies FileLoader falls back to PyMuPDF (fitz) for that page.
        """
        loader = FileLoader(self.pdf_path)

        real_extract = None

        def side_effect_extract(*args, **kwargs):
            raise UnboundLocalError("cannot access local variable 'v' where it is not associated with a value")

        with patch("pypdf._page.PageObject.extract_text", side_effect=side_effect_extract):
            docs = loader.load()
            self.assertEqual(len(docs), 2)
            self.assertIn("Yukti Page 1 Content", docs[0].page_content)
            self.assertIn("Yukti Page 2 Content", docs[1].page_content)

    def test_page_failure_in_both_parsers_raises_runtime_error(self):
        """
        Verifies that if a page fails in both pypdf and PyMuPDF, FileLoader
        does NOT silently drop the page or report partial success, but raises RuntimeError.
        """
        loader = FileLoader(self.pdf_path)

        mock_fitz_page = MagicMock()
        mock_fitz_page.get_text.side_effect = Exception("PyMuPDF C-level decode failure")
        mock_fitz_doc = MagicMock()
        mock_fitz_doc.__len__.return_value = 2
        mock_fitz_doc.__getitem__.return_value = mock_fitz_page

        with patch("pypdf._page.PageObject.extract_text", side_effect=UnboundLocalError("pypdf extraction error")), \
             patch("fitz.open", return_value=mock_fitz_doc):
            with self.assertRaises(RuntimeError) as ctx:
                loader.load()
            self.assertIn("both pypdf", str(ctx.exception))
            self.assertIn("failed", str(ctx.exception))

    def test_pymupdf_retry_parser_exception_raises_runtime_error(self):
        """
        Verifies that when pypdf returns empty text and the PyMuPDF retry block runs,
        any genuine parser exception in PyMuPDF is not silently swallowed and raises RuntimeError.
        """
        loader = FileLoader(self.pdf_path)

        mock_fitz_page = MagicMock()
        mock_fitz_page.get_text.side_effect = Exception("MuPDF stream decompression crash")
        mock_fitz_doc = MagicMock()
        mock_fitz_doc.__iter__.return_value = [mock_fitz_page]

        # pypdf returns empty text without exception
        with patch("pypdf._page.PageObject.extract_text", return_value=""), \
             patch("fitz.open", return_value=mock_fitz_doc):
            with self.assertRaises(RuntimeError) as ctx:
                loader.load()
            self.assertIn("Failed to extract text from page 1 with PyMuPDF", str(ctx.exception))
            self.assertIn("MuPDF stream decompression crash", str(ctx.exception))

    def test_pypdf_reader_failure_fallback_to_fitz(self):
        """
        Simulates a complete pypdf reader failure (e.g. corrupted structure)
        and verifies FileLoader falls back entirely to PyMuPDF.
        """
        loader = FileLoader(self.pdf_path)

        with patch("pypdf.PdfReader", side_effect=Exception("Corrupted pypdf stream")):
            docs = loader.load()
            self.assertEqual(len(docs), 2)
            self.assertIn("Yukti Page 1 Content", docs[0].page_content)
            self.assertIn("Yukti Page 2 Content", docs[1].page_content)

    def test_empty_pdf_raises_value_error(self):
        """Verifies that an empty or image-only PDF raises an informative ValueError."""
        loader = FileLoader(self.blank_pdf_path)
        with self.assertRaises(ValueError) as ctx:
            loader.load()
        self.assertIn("No readable text could be extracted", str(ctx.exception))

    def test_task_status_endpoint_returns_200_on_failure(self):
        """
        Verifies that /api/task/<task_id> returns HTTP 200 with state='failure'
        matching the frontend contract (rather than returning HTTP 500).
        """
        with patch("app.celery.AsyncResult") as mock_async_result:
            mock_res = MagicMock()
            mock_res.state = "FAILURE"
            mock_res.info = "PDF parsing failed: UnboundLocalError"
            mock_async_result.return_value = mock_res

            response = self.client.get("/api/task/task-12345")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["state"], "failure")
            self.assertEqual(data["error"], "PDF parsing failed: UnboundLocalError")

    def test_task_status_endpoint_returns_200_on_success(self):
        """Verifies /api/task/<task_id> returns HTTP 200 with result on task SUCCESS."""
        with patch("app.celery.AsyncResult") as mock_async_result:
            mock_res = MagicMock()
            mock_res.state = "SUCCESS"
            mock_res.result = {"status": "ready", "session_id": "sess-1", "chunk_count": 5}
            mock_async_result.return_value = mock_res

            response = self.client.get("/api/task/task-12345")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["state"], "success")
            self.assertEqual(data["result"]["session_id"], "sess-1")
            self.assertEqual(data["result"]["chunk_count"], 5)

    def test_tasks_process_upload_empty_chunk_validation(self):
        """Verifies tasks.py raises ValueError when chunk_count is 0."""
        from tasks import ProcessUploadTask

        task = ProcessUploadTask()
        task.update_state = MagicMock()

        # Mock loader to return docs, but chunker splits to empty
        with patch("loaders.loader_manager.LoaderManager") as mock_loader_cls, \
             patch("tasks.Chunker") as mock_chunker_cls, \
             patch("tasks.Embedder"), \
             patch("tasks.VectorStore"), \
             patch("tasks.supabase") as mock_supabase:

            mock_loader = MagicMock()
            mock_doc = MagicMock()
            mock_doc.metadata = {"page": 0, "source": "dummy.pdf"}
            mock_loader.load.return_value = [mock_doc]
            mock_loader_cls.return_value = mock_loader

            mock_chunker = MagicMock()
            mock_chunker.split.return_value = []
            mock_chunker_cls.return_value = mock_chunker

            mock_supabase.storage.from_().download.return_value = b"%PDF-1.4 mock content"

            with self.assertRaises(ValueError) as ctx:
                task.process_upload(
                    session_id="dummy-session",
                    filepath="dummy.pdf",
                    title="Dummy",
                    original_filename="dummy.pdf",
                    is_youtube=False
                )
            self.assertIn("No readable text could be extracted", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
