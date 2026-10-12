import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock
from flask import Flask

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

# Ensure required env vars are present before db imports
import dotenv
dotenv.load_dotenv(WORKSPACE_ROOT / ".env")
os.environ.setdefault("SUPABASE_URL", "https://mock.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "mock_key")

from services.otp_service import (
    OTPService,
    OTPStore,
    OTPStorageError,
    OTPProvider,
    mask_target,
    is_production,
)
from routes.auth import auth_bp


class TestOTPServiceAndRoutes(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(auth_bp, url_prefix='/api')
        self.client = self.app.test_client()

    # --- 1. Target Normalization Tests ---
    def test_target_normalization_email(self):
        norm, err = OTPService.normalize_target("  Student.Yukti@Example.COM  ", "email")
        self.assertIsNone(err)
        self.assertEqual(norm, "student.yukti@example.com")

        norm_inv, err_inv = OTPService.normalize_target("not-an-email", "email")
        self.assertIsNotNone(err_inv)
        self.assertIn("Invalid email", err_inv)

    def test_target_normalization_phone(self):
        norm, err = OTPService.normalize_target("+1 (555) 234-5678", "phone")
        self.assertIsNone(err)
        self.assertEqual(norm, "+15552345678")

        norm_inv, err_inv = OTPService.normalize_target("abc-123", "phone")
        self.assertIsNotNone(err_inv)
        self.assertIn("Invalid phone", err_inv)

    def test_mask_target(self):
        self.assertEqual(mask_target("student@example.com"), "st***@example.com")
        self.assertEqual(mask_target("+15552345678"), "+15****78")
        self.assertEqual(mask_target(""), "****")

    # --- 2. In-Memory Store & Security Isolation Tests (Dev/Testing Mode) ---
    def test_store_purpose_isolation(self):
        store = OTPStore()
        # Force in-memory mode
        store._use_redis = False
        store._redis_client = None

        with patch("services.otp_service.is_production", return_value=False):
            store.save("test@example.com", "123456", ttl_seconds=300, purpose="login")

            # Check that "login" code cannot be accessed for "password_reset"
            rec_reset = store.get("test@example.com", purpose="password_reset")
            self.assertIsNone(rec_reset)

            # Check that "login" code is returned for "login" purpose
            rec_login = store.get("test@example.com", purpose="login")
            self.assertIsNotNone(rec_login)
            self.assertEqual(rec_login["otp"], "123456")

    def test_store_attempt_limiting_and_invalidation(self):
        with patch("services.otp_service.is_production", return_value=False):
            with patch("services.otp_service.OTPProvider._is_mock_allowed", return_value=True):
                target = "attempts@example.com"
                success, msg, meta = OTPService.send_otp(target, "email", purpose="login")
                self.assertTrue(success)

                # Attempt 1: Wrong code
                ok, msg1 = OTPService.verify_otp(target, "email", "000000", purpose="login")
                self.assertFalse(ok)
                self.assertIn("2 attempt(s) remaining", msg1)

                # Attempt 2: Wrong code
                ok, msg2 = OTPService.verify_otp(target, "email", "000000", purpose="login")
                self.assertFalse(ok)
                self.assertIn("1 attempt(s) remaining", msg2)

                # Attempt 3: Wrong code -> invalidated
                ok, msg3 = OTPService.verify_otp(target, "email", "000000", purpose="login")
                self.assertFalse(ok)
                self.assertIn("invalidated", msg3.lower())

                # Subsequent attempt should report expired/not requested
                ok, msg4 = OTPService.verify_otp(target, "email", "000000", purpose="login")
                self.assertFalse(ok)
                self.assertIn("expired", msg4.lower())

    def test_store_single_use_consumption(self):
        with patch("services.otp_service.is_production", return_value=False):
            with patch("services.otp_service.OTPProvider._is_mock_allowed", return_value=True):
                target = "singleuse@example.com"
                with patch.dict(os.environ, {"TESTING": "true"}):
                    success, _, meta = OTPService.send_otp(target, "email", purpose="login")
                    self.assertTrue(success)
                    code = meta.get("debug_otp")

                    # First verification succeeds
                    ok1, msg1 = OTPService.verify_otp(target, "email", code, purpose="login")
                    self.assertTrue(ok1)
                    self.assertIn("successfully", msg1.lower())

                    # Second verification must fail because code was deleted
                    ok2, msg2 = OTPService.verify_otp(target, "email", code, purpose="login")
                    self.assertFalse(ok2)
                    self.assertIn("expired", msg2.lower())

    # --- 3. Strict Production Fail-Safe Tests (Constraint 3) ---
    def test_production_failsafe_blocks_in_memory_when_redis_unavailable(self):
        """In production, OTPStore MUST NOT fall back to in-memory store if Redis is absent."""
        store = OTPStore()
        store._use_redis = False
        store._redis_client = None

        with patch("services.otp_service.is_production", return_value=True):
            with self.assertRaises(OTPStorageError):
                store.save("prod@example.com", "123456", purpose="login")

            with self.assertRaises(OTPStorageError):
                store.get("prod@example.com", purpose="login")

            with self.assertRaises(OTPStorageError):
                store.can_resend("prod@example.com", purpose="login")

            with self.assertRaises(OTPStorageError):
                store.check_ip_rate_limit("198.51.100.1")

            with self.assertRaises(OTPStorageError):
                store.save_reset_token("reset-tok-123", 1, "prod@example.com")

            with self.assertRaises(OTPStorageError):
                store.consume_reset_token("reset-tok-123")

    def test_production_provider_disallows_mock_otp(self):
        """In production without SMTP configured and without ALLOW_MOCK_OTP, email dispatch fails safe."""
        with patch("services.otp_service.is_production", return_value=True):
            with patch.dict(os.environ, {
                "FLASK_ENV": "production",
                "ALLOW_MOCK_OTP": "",
                "SMTP_HOST": "",
                "SMTP_USER": "",
                "SMTP_PASS": "",
                "TESTING": "",
                "YUKTI_TEST_MODE": ""
            }):
                success, msg = OTPProvider.send_email("user@example.com", "123456")
                self.assertFalse(success)
                self.assertIn("not configured", msg.lower())

    # --- 4. Password Reset Token Lifecycle ---
    def test_password_reset_token_single_use(self):
        with patch("services.otp_service.is_production", return_value=False):
            token = OTPService.create_password_reset_token(42, "user@example.com")
            self.assertTrue(len(token) > 20)

            # Atomic verification and consumption
            valid, msg, record = OTPService.verify_and_consume_password_reset_token(token)
            self.assertTrue(valid)
            self.assertEqual(record["user_id"], 42)
            self.assertEqual(record["target"], "user@example.com")

            # Second consumption must fail (preventing replay attacks)
            valid2, msg2, record2 = OTPService.verify_and_consume_password_reset_token(token)
            self.assertFalse(valid2)
            self.assertIsNone(record2)

    # --- 5. Flask Auth Route Contract Tests ---
    @patch("services.otp_service.is_production", return_value=False)
    @patch("services.otp_service.OTPProvider._is_mock_allowed", return_value=True)
    def test_route_send_otp_success(self, mock_mock_allowed, mock_prod):
        resp = self.client.post(
            "/api/auth/otp/send",
            json={"target": "student@yukti.org", "type": "email"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("target", data)
        self.assertEqual(data["expires_in"], 300)

    def test_route_send_otp_invalid_target(self):
        resp = self.client.post(
            "/api/auth/otp/send",
            json={"target": "not-an-email", "type": "email"}
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data["error"], "otp_send_failed")

    @patch("services.otp_service.is_production", return_value=False)
    @patch("services.otp_service.OTPProvider._is_mock_allowed", return_value=True)
    @patch("routes.auth.get_user_by_username")
    @patch("routes.auth.save_user")
    @patch("routes.auth.get_user_by_id")
    @patch("routes.auth.create_auth_token")
    def test_route_verify_otp_success_creates_user_and_issues_token(
        self,
        mock_create_token,
        mock_get_user_by_id,
        mock_save_user,
        mock_get_user_by_name,
        mock_mock_allowed,
        mock_prod
    ):
        mock_get_user_by_name.return_value = None  # New user
        mock_save_user.return_value = 99
        mock_get_user_by_id.return_value = {
            "id": 99,
            "username": "newlearner@yukti.org",
            "created_at": "2026-10-12T00:00:00Z"
        }

        with patch.dict(os.environ, {"TESTING": "true"}):
            # Send OTP first
            send_resp = self.client.post(
                "/api/auth/otp/send",
                json={"target": "newlearner@yukti.org", "type": "email"}
            )
            self.assertEqual(send_resp.status_code, 200)
            code = send_resp.get_json().get("debug_otp")
            self.assertIsNotNone(code)

            # Verify OTP
            verify_resp = self.client.post(
                "/api/auth/otp/verify",
                json={"target": "newlearner@yukti.org", "type": "email", "otp": code}
            )
            self.assertEqual(verify_resp.status_code, 200)
            data = verify_resp.get_json()
            self.assertTrue(data["success"])
            self.assertIn("token", data)
            self.assertEqual(data["user"]["id"], 99)
            self.assertEqual(data["user"]["username"], "newlearner@yukti.org")

            # Check that create_auth_token was called with the user id and token
            mock_create_token.assert_called_once_with(99, data["token"])

    @patch("services.otp_service.is_production", return_value=True)
    def test_route_production_redis_failure_returns_503(self, mock_prod):
        """When Redis is unavailable in production, the API returns HTTP 503 instead of corrupting memory."""
        # Ensure store has no redis
        from services.otp_service import _otp_store
        orig_redis = _otp_store._use_redis
        orig_client = _otp_store._redis_client
        _otp_store._use_redis = False
        _otp_store._redis_client = None

        try:
            resp = self.client.post(
                "/api/auth/otp/send",
                json={"target": "prod@yukti.org", "type": "email"}
            )
            self.assertEqual(resp.status_code, 503)
            data = resp.get_json()
            self.assertEqual(data["error"], "service_unavailable")
        finally:
            _otp_store._use_redis = orig_redis
            _otp_store._redis_client = orig_client

    @patch("utils.auth.get_user_id_by_token")
    @patch("routes.auth.get_user_by_id")
    @patch("routes.auth.list_session_data")
    def test_token_compatibility_with_require_auth(self, mock_list_sessions, mock_get_user, mock_get_uid):
        """Verifies that an opaque token issued by verify_otp is accepted by require_auth."""
        mock_get_uid.return_value = 42
        mock_get_user.return_value = {
            "id": 42,
            "username": "learner42@example.com",
            "created_at": "2026-10-12T00:00:00Z"
        }
        mock_list_sessions.return_value = []

        resp = self.client.get(
            "/api/me",
            headers={"Authorization": "Bearer mock-otp-issued-token"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["username"], "learner42@example.com")

    # --- 6. Security Hardening Tests ---
    @patch("services.otp_service.is_production", return_value=False)
    @patch("services.otp_service.OTPProvider._is_mock_allowed", return_value=True)
    @patch("routes.auth.get_user_by_email")
    @patch("routes.auth.get_user_by_username")
    def test_account_enumeration_resistance_password_reset(self, mock_by_name, mock_by_email, mock_mock, mock_prod):
        """Verifies that password reset public responses are identical for existing and non-existing accounts."""
        # 1. Existing user
        mock_by_email.return_value = {"id": 10, "username": "existing@yukti.org"}
        mock_by_name.return_value = None

        resp_exist_1 = self.client.post("/api/auth/password-reset/request", json={"email": "existing@yukti.org"})
        self.assertEqual(resp_exist_1.status_code, 200)
        data_exist_1 = resp_exist_1.get_json()

        # Repeated request within cooldown
        resp_exist_2 = self.client.post("/api/auth/password-reset/request", json={"email": "existing@yukti.org"})
        self.assertEqual(resp_exist_2.status_code, 200)
        data_exist_2 = resp_exist_2.get_json()

        # 2. Non-existing user
        mock_by_email.return_value = None
        mock_by_name.return_value = None

        resp_none_1 = self.client.post("/api/auth/password-reset/request", json={"email": "ghost@yukti.org"})
        self.assertEqual(resp_none_1.status_code, 200)
        data_none_1 = resp_none_1.get_json()

        # Repeated request within cooldown for non-existing user
        resp_none_2 = self.client.post("/api/auth/password-reset/request", json={"email": "ghost@yukti.org"})
        self.assertEqual(resp_none_2.status_code, 200)
        data_none_2 = resp_none_2.get_json()

        # Public responses must be completely identical
        self.assertEqual(data_exist_1, data_none_1)
        self.assertEqual(data_exist_2, data_none_2)
        self.assertEqual(data_exist_1["message"], data_exist_2["message"])

    @patch("services.otp_service.is_production", return_value=False)
    @patch("services.otp_service.OTPProvider._is_mock_allowed", return_value=True)
    @patch("routes.auth.get_user_by_email")
    @patch("routes.auth.get_user_by_username")
    def test_account_enumeration_resistance_username_recovery(self, mock_by_name, mock_by_email, mock_mock, mock_prod):
        """Verifies that username recovery public responses are identical for existing and non-existing accounts."""
        # 1. First attempt: existing user
        mock_by_email.return_value = {"id": 20, "username": "realuser@yukti.org"}
        mock_by_name.return_value = None

        resp_exist = self.client.post("/api/auth/username-recovery/request", json={"email": "realuser@yukti.org"})
        self.assertEqual(resp_exist.status_code, 200)

        # 2. First attempt: non-existing user
        mock_by_email.return_value = None
        mock_by_name.return_value = None

        resp_none = self.client.post("/api/auth/username-recovery/request", json={"email": "nosuchuser@yukti.org"})
        self.assertEqual(resp_none.status_code, 200)
        self.assertEqual(resp_exist.get_json(), resp_none.get_json())

        # 3. Verify attempt for non-existing user returns 400 (verification_failed), never 404 (not_found)
        verify_resp = self.client.post("/api/auth/username-recovery/verify", json={"email": "nosuchuser@yukti.org", "otp": "999999"})
        self.assertEqual(verify_resp.status_code, 400)
        self.assertEqual(verify_resp.get_json()["error"], "verification_failed")

    def test_client_ip_extraction_security(self):
        """Verifies that get_client_ip never trusts spoofed headers unless coming from an authorized proxy."""
        from routes.auth import get_client_ip

        # Case A: Untrusted direct connection with spoofed header -> ignore header
        with self.app.test_request_context("/", environ_base={"REMOTE_ADDR": "203.0.113.50"}, headers={"X-Forwarded-For": "1.2.3.4"}):
            with patch.dict(os.environ, {"TRUSTED_PROXIES": ""}):
                ip = get_client_ip()
                self.assertEqual(ip, "203.0.113.50")

        # Case B: Insecure wildcard TRUSTED_PROXIES='*' -> disallowed, ignores header
        with self.app.test_request_context("/", environ_base={"REMOTE_ADDR": "203.0.113.50"}, headers={"X-Forwarded-For": "1.2.3.4"}):
            with patch.dict(os.environ, {"TRUSTED_PROXIES": "*"}):
                ip = get_client_ip()
                self.assertEqual(ip, "203.0.113.50")

        # Case C: Direct client not in TRUSTED_PROXIES list -> ignore header
        with self.app.test_request_context("/", environ_base={"REMOTE_ADDR": "198.51.100.22"}, headers={"X-Forwarded-For": "8.8.8.8"}):
            with patch.dict(os.environ, {"TRUSTED_PROXIES": "10.0.0.1, 127.0.0.1"}):
                ip = get_client_ip()
                self.assertEqual(ip, "198.51.100.22")

        # Case D: Authorized proxy in TRUSTED_PROXIES -> extract leftmost valid client IP
        with self.app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.1"}, headers={"X-Forwarded-For": "203.0.113.195, 10.0.0.1"}):
            with patch.dict(os.environ, {"TRUSTED_PROXIES": "127.0.0.1"}):
                ip = get_client_ip()
                self.assertEqual(ip, "203.0.113.195")

        # Case E: Authorized proxy with malformed header -> fallback to remote_addr safely
        with self.app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.1"}, headers={"X-Forwarded-For": "evil<script>, not-an-ip"}):
            with patch.dict(os.environ, {"TRUSTED_PROXIES": "127.0.0.1"}):
                ip = get_client_ip()
                self.assertEqual(ip, "127.0.0.1")

    def test_otp_verification_concurrency_and_atomicity(self):
        """Verifies that concurrent verification of the same code allows exactly ONE success and no double-spend."""
        import concurrent.futures

        with patch("services.otp_service.is_production", return_value=False):
            with patch("services.otp_service.OTPProvider._is_mock_allowed", return_value=True):
                target = "race@yukti.org"
                with patch.dict(os.environ, {"TESTING": "true"}):
                    _, _, meta = OTPService.send_otp(target, "email", purpose="login")
                    code = meta["debug_otp"]

                    results = []
                    # Launch 5 concurrent verification attempts with the exact same valid OTP
                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        futures = [
                            executor.submit(OTPService.verify_otp, target, "email", code, purpose="login")
                            for _ in range(5)
                        ]
                        for f in concurrent.futures.as_completed(futures):
                            results.append(f.result())

                    successes = [r for r in results if r[0] is True]
                    failures = [r for r in results if r[0] is False]

                    # Exactly ONE thread can consume the OTP; the others must fail
                    self.assertEqual(len(successes), 1)
                    self.assertEqual(len(failures), 4)
                    self.assertIn("expired", failures[0][1].lower())


if __name__ == "__main__":
    unittest.main()
