import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import dotenv
dotenv.load_dotenv(WORKSPACE_ROOT / ".env")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy-service-key")

import httpx
import postgrest
from postgrest._sync.request_builder import SyncQueryRequestBuilder
from supabase import create_client
import db


class TestDbResilience(unittest.TestCase):
    def test_postgrest_session_uses_http1(self):
        """PostgREST client must configure http2=False to prevent idle GOAWAY connection drops."""
        # 1. Direct verify on db.supabase client
        client = db.supabase
        self.assertFalse(
            client.postgrest.session._transport._pool._http2,
            "PostgREST HTTP pool must have http2=False"
        )

        # 2. Verify new session creation from client also uses http2=False
        session = client.postgrest.create_session(
            base_url="https://example.supabase.co/rest/v1",
            headers={},
            timeout=10,
        )
        self.assertFalse(
            session._transport._pool._http2,
            "Newly created PostgREST session must have http2=False"
        )

        # 3. Verify subsequently instantiated clients also inherit http2=False
        new_client = create_client(
            os.environ.get("SUPABASE_URL", "https://example.supabase.co"),
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "dummy-service-key"),
        )
        self.assertFalse(
            new_client.postgrest.session._transport._pool._http2,
            "Subsequently created Supabase Client must inherit http2=False"
        )

    def test_query_execute_retries_on_remote_protocol_error(self):
        """SyncQueryRequestBuilder.execute retries once upon RemoteProtocolError for GET queries."""
        builder = db.supabase.table("sessions").select("session_id")
        self.assertEqual(builder.http_method, "GET")
        mock_result = MagicMock()
        mock_result.data = [{"session_id": "test-123"}]

        with patch.object(
            db,
            "_orig_query_execute",
            side_effect=[httpx.RemoteProtocolError("<ConnectionTerminated error_code:0>"), mock_result]
        ) as mock_exec:
            res = builder.execute()
            self.assertEqual(res, mock_result)
            self.assertEqual(mock_exec.call_count, 2)

    def test_query_execute_retries_on_connect_error(self):
        """SyncQueryRequestBuilder.execute retries once upon transient ConnectError for GET queries."""
        builder = db.supabase.table("sessions").select("session_id")
        self.assertEqual(builder.http_method, "GET")
        mock_result = MagicMock()
        mock_result.data = [{"session_id": "test-123"}]

        with patch.object(
            db,
            "_orig_query_execute",
            side_effect=[httpx.ConnectError("Connection reset by peer"), mock_result]
        ) as mock_exec:
            res = builder.execute()
            self.assertEqual(res, mock_result)
            self.assertEqual(mock_exec.call_count, 2)

    def test_query_execute_retries_on_head_method(self):
        """SyncQueryRequestBuilder.execute retries once for HEAD (count) queries."""
        builder = db.supabase.table("sessions").select("session_id", count="exact")
        builder.http_method = "HEAD"
        mock_result = MagicMock()

        with patch.object(
            db,
            "_orig_query_execute",
            side_effect=[httpx.ReadTimeout("Socket read timeout"), mock_result]
        ) as mock_exec:
            res = builder.execute()
            self.assertEqual(res, mock_result)
            self.assertEqual(mock_exec.call_count, 2)

    def test_query_execute_raises_if_retry_also_fails(self):
        """If transient failure persists across retry, the exception is raised."""
        builder = db.supabase.table("sessions").select("session_id")

        with patch.object(
            db,
            "_orig_query_execute",
            side_effect=[
                httpx.RemoteProtocolError("First error"),
                httpx.RemoteProtocolError("Second error"),
            ]
        ) as mock_exec:
            with self.assertRaises(httpx.RemoteProtocolError):
                builder.execute()
            self.assertEqual(mock_exec.call_count, 2)

    def test_query_execute_does_not_retry_write_mutations(self):
        """Non-idempotent write operations (POST, PATCH, DELETE) must NOT be retried to prevent duplicate mutations."""
        # Test POST (insert)
        insert_builder = db.supabase.table("sessions").insert({"session_id": "test-insert"})
        self.assertEqual(insert_builder.http_method, "POST")
        with patch.object(
            db,
            "_orig_query_execute",
            side_effect=httpx.RemoteProtocolError("ConnectionTerminated")
        ) as mock_exec:
            with self.assertRaises(httpx.RemoteProtocolError):
                insert_builder.execute()
            self.assertEqual(mock_exec.call_count, 1, "POST must not be retried")

        # Test PATCH (update)
        update_builder = db.supabase.table("sessions").update({"filename": "test"}).eq("session_id", "123")
        self.assertEqual(update_builder.http_method, "PATCH")
        with patch.object(
            db,
            "_orig_query_execute",
            side_effect=httpx.ConnectError("Connection failed")
        ) as mock_exec:
            with self.assertRaises(httpx.ConnectError):
                update_builder.execute()
            self.assertEqual(mock_exec.call_count, 1, "PATCH must not be retried")

        # Test DELETE
        delete_builder = db.supabase.table("sessions").delete().eq("session_id", "123")
        self.assertEqual(delete_builder.http_method, "DELETE")
        with patch.object(
            db,
            "_orig_query_execute",
            side_effect=httpx.ReadTimeout("Timeout")
        ) as mock_exec:
            with self.assertRaises(httpx.ReadTimeout):
                delete_builder.execute()
            self.assertEqual(mock_exec.call_count, 1, "DELETE must not be retried")

    def test_query_execute_does_not_retry_unrelated_errors(self):
        """Non-transport errors (e.g. ValueError, APIError) should raise immediately without retry."""
        builder = db.supabase.table("sessions").select("session_id")

        with patch.object(
            db,
            "_orig_query_execute",
            side_effect=ValueError("Invalid query parameter")
        ) as mock_exec:
            with self.assertRaises(ValueError):
                builder.execute()
            self.assertEqual(mock_exec.call_count, 1)


if __name__ == "__main__":
    unittest.main()
