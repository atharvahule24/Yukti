import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock
from flask import Flask

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import dotenv
dotenv.load_dotenv(WORKSPACE_ROOT / ".env")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_key")

from routes.sessions import sessions_bp, determine_session_status


class TestSessionLifecycle(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(sessions_bp, url_prefix='/api')
        self.client = self.app.test_client()

    def test_determine_session_status_explicit_states(self):
        """Validates determine_session_status with explicit status values."""
        self.assertEqual(determine_session_status({"status": "ready"}), "ready")
        self.assertEqual(determine_session_status({"status": "completed"}), "ready")
        self.assertEqual(determine_session_status({"status": "failed"}), "failed")
        self.assertEqual(determine_session_status({"status": "failure"}), "failed")
        self.assertEqual(determine_session_status({"status": "error"}), "failed")

    def test_determine_session_status_processing_staleness(self):
        """Recent processing stays processing; old processing (>15m) becomes failed."""
        now = datetime.now(timezone.utc)
        recent_iso = (now - timedelta(minutes=10)).isoformat()
        stale_iso = (now - timedelta(hours=2)).isoformat()

        self.assertEqual(
            determine_session_status({"status": "processing", "created_at": recent_iso}),
            "processing"
        )
        self.assertEqual(
            determine_session_status({"status": "processing", "created_at": stale_iso}),
            "failed"
        )

    @patch('celery_app.celery.AsyncResult')
    def test_determine_session_status_with_celery_task_state(self, mock_async_result):
        """Active Celery uploads (PROGRESS/PENDING) are NEVER marked failed solely due to age."""
        now = datetime.now(timezone.utc)
        old_iso = (now - timedelta(minutes=45)).isoformat()

        # Task actively in PROGRESS after 45 minutes
        mock_task = MagicMock()
        mock_task.state = "PROGRESS"
        mock_async_result.return_value = mock_task

        status = determine_session_status({
            "status": "processing",
            "task_id": "long-running-task-id",
            "created_at": old_iso
        })
        self.assertEqual(status, "processing")

        # Task PENDING/queued
        mock_task.state = "PENDING"
        status = determine_session_status({
            "status": "processing",
            "task_id": "queued-task-id",
            "created_at": old_iso
        })
        self.assertEqual(status, "processing")

        # Task confirmed FAILURE
        mock_task.state = "FAILURE"
        status = determine_session_status({
            "status": "processing",
            "task_id": "failed-task-id",
            "created_at": old_iso
        })
        self.assertEqual(status, "failed")

        # Task confirmed SUCCESS
        mock_task.state = "SUCCESS"
        status = determine_session_status({
            "status": "processing",
            "task_id": "done-task-id",
            "created_at": old_iso
        })
        self.assertEqual(status, "ready")

    def test_determine_session_status_legacy_records(self):
        """Legacy sessions without explicit status are classified by text/chunk presence and age."""
        now = datetime.now(timezone.utc)
        recent_iso = (now - timedelta(minutes=2)).isoformat()
        stale_iso = (now - timedelta(days=2)).isoformat()

        # Legacy ready: has chunks or text
        self.assertEqual(
            determine_session_status({"created_at": stale_iso, "chunk_count": 12, "full_text": ""}),
            "ready"
        )
        self.assertEqual(
            determine_session_status({"created_at": stale_iso, "chunk_count": 0, "full_text": "Extracted doc content"}),
            "ready"
        )

        # Legacy empty: recent is considered processing, stale is considered failed
        self.assertEqual(
            determine_session_status({"created_at": recent_iso, "chunk_count": 0, "full_text": ""}),
            "processing"
        )
        self.assertEqual(
            determine_session_status({"created_at": stale_iso, "chunk_count": 0, "full_text": ""}),
            "failed"
        )

    @patch('utils.auth.get_user_id_by_token')
    @patch('routes.sessions.list_session_data')
    def test_get_sessions_filters_failed_and_deduplicates(self, mock_list_sessions, mock_get_user):
        """get_sessions should exclude failed/stale sessions, keep ready/processing, and deduplicate."""
        mock_get_user.return_value = 101
        now = datetime.now(timezone.utc)

        raw_sessions = [
            {
                "id": "sess-ready-1",
                "session_id": "sess-ready-1",
                "title": "Quantum Computing",
                "created_at": (now - timedelta(minutes=5)).isoformat(),
                "status": "ready",
                "chunk_count": 18,
                "full_text": "Sample text",
            },
            {
                # Duplicate ID of sess-ready-1
                "id": "sess-ready-1",
                "session_id": "sess-ready-1",
                "title": "Quantum Computing Duplicate",
                "created_at": (now - timedelta(minutes=5)).isoformat(),
                "status": "ready",
                "chunk_count": 18,
            },
            {
                "id": "sess-processing-1",
                "session_id": "sess-processing-1",
                "title": "Machine Learning Lecture",
                "created_at": (now - timedelta(minutes=2)).isoformat(),
                "status": "processing",
                "chunk_count": 0,
                "full_text": "",
            },
            {
                "id": "sess-failed-explicit",
                "session_id": "sess-failed-explicit",
                "title": "Broken Battery PDF",
                "created_at": (now - timedelta(hours=1)).isoformat(),
                "status": "failed",
                "chunk_count": 0,
                "full_text": "",
            },
            {
                "id": "sess-failed-stale",
                "session_id": "sess-failed-stale",
                "title": "Old Empty Failed Session",
                "created_at": (now - timedelta(days=1)).isoformat(),
                "chunk_count": 0,
                "full_text": "",
            },
        ]
        mock_list_sessions.return_value = raw_sessions

        resp = self.client.get(
            '/api/sessions',
            headers={'Authorization': 'Bearer test-token'}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("sessions", data)
        sessions = data["sessions"]

        # Only sess-ready-1 and sess-processing-1 should remain (2 items)
        self.assertEqual(len(sessions), 2)

        returned_ids = [s["id"] for s in sessions]
        self.assertIn("sess-ready-1", returned_ids)
        self.assertIn("sess-processing-1", returned_ids)
        self.assertNotIn("sess-failed-explicit", returned_ids)
        self.assertNotIn("sess-failed-stale", returned_ids)

        # Check status fields
        ready_sess = next(s for s in sessions if s["id"] == "sess-ready-1")
        self.assertEqual(ready_sess["status"], "ready")
        self.assertEqual(ready_sess["chunk_count"], 18)

        proc_sess = next(s for s in sessions if s["id"] == "sess-processing-1")
        self.assertEqual(proc_sess["status"], "processing")

    @patch('tasks.supabase')
    @patch('tasks.session_store')
    def test_process_upload_failure_updates_session_store(self, mock_store, mock_sb):
        """When process_upload fails, it records status='failed' in session_store before raising."""
        from tasks import ProcessUploadTask

        task = ProcessUploadTask()
        task.update_state = MagicMock()

        mock_store.get.return_value = {"id": "sess-test-err", "title": "Test Doc"}
        mock_storage = MagicMock()
        mock_sb.storage.from_.return_value = mock_storage
        mock_storage.download.side_effect = RuntimeError("Supabase storage read failed")

        with self.assertRaises(RuntimeError):
            task.process_upload(
                session_id="sess-test-err",
                filepath="uploads/corrupt.pdf",
                title="Test Doc",
                original_filename="corrupt.pdf",
                is_youtube=False
            )

        # Verify session_store was updated with failed status
        self.assertTrue(mock_store.__setitem__.called)
        call_args = mock_store.__setitem__.call_args
        saved_session = call_args[0][1]
        self.assertEqual(saved_session["status"], "failed")
        self.assertEqual(saved_session["id"], "sess-test-err")
        self.assertIn("Supabase storage read failed", saved_session["error"])
        self.assertEqual(saved_session["chunk_count"], 0)


if __name__ == '__main__':
    unittest.main()
