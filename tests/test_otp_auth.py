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
    @patch("services.otp_service.OTPProvider.send_email")
    def test_route_send_otp_ambiguous_delivery_returns_metadata_and_preserves_otp(self, mock_send_email, mock_prod):
        """Verifies that route /api/auth/otp/send returns HTTP 400 with ambiguous_delivery: True on read timeout."""
        from services.otp_service import EmailDispatchResult, _otp_store
        mock_send_email.return_value = EmailDispatchResult(
            False,
            "Failed to send verification email. Delivery could not be confirmed; please check your inbox or try again.",
            is_ambiguous=True
        )

        with patch.dict(os.environ, {"RESEND_API_KEY": "re_mock_test_key", "ALLOW_MOCK_OTP": "false"}):
            resp = self.client.post(
                "/api/auth/otp/send",
                json={"target": "ambiguous_learner@yukti.org", "type": "email"}
            )
            self.assertEqual(resp.status_code, 400)
            data = resp.get_json()
            self.assertEqual(data["error"], "otp_send_failed")
            self.assertTrue(data.get("ambiguous_delivery"))
            self.assertIn("could not be confirmed", data["message"])
            # OTP must remain in store
            record = _otp_store.get("ambiguous_learner@yukti.org", purpose="login")
            self.assertIsNotNone(record)

    @patch("services.otp_service.is_production", return_value=False)
    @patch("services.otp_service.OTPProvider.send_email")
    def test_route_send_otp_definitive_failure_does_not_return_ambiguous_flag(self, mock_send_email, mock_prod):
        """Verifies that route /api/auth/otp/send returns HTTP 400 without ambiguous_delivery on definitive rejection."""
        from services.otp_service import EmailDispatchResult, _otp_store
        mock_send_email.return_value = EmailDispatchResult(
            False,
            "Failed to send verification email. Please try again later.",
            is_ambiguous=False
        )

        with patch.dict(os.environ, {"RESEND_API_KEY": "re_mock_test_key", "ALLOW_MOCK_OTP": "false"}):
            resp = self.client.post(
                "/api/auth/otp/send",
                json={"target": "rejected_learner@yukti.org", "type": "email"}
            )
            self.assertEqual(resp.status_code, 400)
            data = resp.get_json()
            self.assertEqual(data["error"], "otp_send_failed")
            self.assertFalse(data.get("ambiguous_delivery", False))
            self.assertEqual(data["message"], "Failed to send verification email. Please try again later.")
            # OTP must be purged from store
            record = _otp_store.get("rejected_learner@yukti.org", purpose="login")
            self.assertIsNone(record)

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

    # --- 7. Resend HTTPS Provider Focused Tests ---
    @patch("urllib.request.urlopen")
    def test_resend_send_email_success(self, mock_urlopen):
        """Verifies successful email dispatch via Resend HTTPS API with required headers and payload."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        env_vars = {
            "RESEND_API_KEY": "re_mock_test_key_12345",
            "RESEND_FROM": "Yukti Auth <auth@testdomain.com>",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.send_email("learner@example.com", "654321", purpose="login")
            self.assertTrue(success)
            self.assertEqual(msg, "Email sent successfully.")

            mock_urlopen.assert_called_once()
            call_args, call_kwargs = mock_urlopen.call_args
            req = call_args[0]

            self.assertEqual(req.full_url, "https://api.resend.com/emails")
            self.assertEqual(req.get_method(), "POST")
            self.assertEqual(req.headers.get("Authorization"), "Bearer re_mock_test_key_12345")
            self.assertEqual(req.headers.get("Content-type"), "application/json")
            self.assertEqual(req.headers.get("User-agent"), "Yukti/1.0")
            self.assertEqual(call_kwargs.get("timeout"), 10)

            import json
            payload = json.loads(req.data.decode("utf-8"))
            self.assertEqual(payload["from"], "Yukti Auth <auth@testdomain.com>")
            self.assertEqual(payload["to"], ["learner@example.com"])
            self.assertIn("654321", payload["text"])

    @patch("urllib.request.urlopen")
    def test_resend_send_email_authorization_failure(self, mock_urlopen):
        """Verifies that Resend 401 Unauthorized returns graceful error and does NOT fall back to SMTP."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://api.resend.com/emails", 401, "Unauthorized", {}, None
        )

        env_vars = {
            "RESEND_API_KEY": "re_invalid_key",
            "SMTP_HOST": "smtp.gmail.com",
            "SMTP_USER": "test@gmail.com",
            "SMTP_PASS": "pass",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            with patch("smtplib.SMTP") as mock_smtp:
                success, msg = OTPProvider.send_email("learner@example.com", "654321", purpose="login")
                self.assertFalse(success)
                self.assertIn("Failed to send verification email", msg)
                # Resend must NOT fall back to SMTP when configured
                mock_smtp.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_resend_send_email_http_error(self, mock_urlopen):
        """Verifies that Resend 403 Forbidden returns graceful error without crashing."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://api.resend.com/emails", 403, "Forbidden", {}, None
        )

        env_vars = {"RESEND_API_KEY": "re_mock_key"}
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.send_email("learner@example.com", "654321", purpose="login")
            self.assertFalse(success)
            self.assertIn("Failed to send verification email", msg)

    @patch("urllib.request.urlopen")
    def test_resend_send_email_timeout(self, mock_urlopen):
        """Verifies that Resend timeout returns graceful error without crashing."""
        mock_urlopen.side_effect = TimeoutError("The read operation timed out")

        env_vars = {"RESEND_API_KEY": "re_mock_key"}
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.send_email("learner@example.com", "654321", purpose="login")
            self.assertFalse(success)
            self.assertIn("Failed to send verification email", msg)

    @patch("urllib.request.urlopen")
    def test_resend_otp_cleanup_on_failure(self, mock_urlopen):
        """Verifies that OTP is purged from store when Resend dispatch fails."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://api.resend.com/emails", 500, "Internal Server Error", {}, None
        )

        env_vars = {"RESEND_API_KEY": "re_mock_key", "ALLOW_MOCK_OTP": "false"}
        with patch.dict(os.environ, env_vars, clear=False):
            with patch("services.otp_service._otp_store.delete") as mock_delete:
                with patch("services.otp_service._otp_store.can_resend", return_value=(True, 0)):
                    with patch("services.otp_service._otp_store.save"):
                        success, msg, meta = OTPService.send_otp("learner@example.com", "email", purpose="login")
                        self.assertFalse(success)
                        mock_delete.assert_called_once_with("learner@example.com", purpose="login")

    @patch("smtplib.SMTP")
    def test_resend_absent_falls_back_to_smtp(self, mock_smtp):
        """Verifies that when RESEND_API_KEY is absent, SMTP configuration is used."""
        mock_instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_instance

        env_vars = {
            "RESEND_API_KEY": "",
            "SMTP_HOST": "smtp.custom.org",
            "SMTP_PORT": "587",
            "SMTP_USER": "custom_user@custom.org",
            "SMTP_PASS": "custom_pass",
            "ALLOW_MOCK_OTP": "false"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.send_email("learner@example.com", "123456", purpose="login")
            self.assertTrue(success)
            mock_smtp.assert_called_once_with("smtp.custom.org", 587, timeout=10)

    @patch("urllib.request.urlopen")
    def test_resend_send_email_202_accepted(self, mock_urlopen):
        """Verifies that non-200 2xx status (HTTP 202 Accepted) is accepted as success."""
        mock_resp = MagicMock()
        mock_resp.status = 202
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        env_vars = {
            "RESEND_API_KEY": "re_mock_test_key_12345",
            "RESEND_FROM": "Yukti Auth <auth@testdomain.com>",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.send_email("learner@example.com", "654321", purpose="login")
            self.assertTrue(success)
            self.assertEqual(msg, "Email sent successfully.")

    @patch("urllib.request.urlopen")
    def test_resend_timeout_ambiguous_preserves_otp_in_store(self, mock_urlopen):
        """Verifies that network timeout marks delivery ambiguous and preserves OTP in store for verification."""
        mock_urlopen.side_effect = TimeoutError("The read operation timed out")

        env_vars = {
            "RESEND_API_KEY": "re_mock_key",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            with patch("services.otp_service._otp_store.delete") as mock_delete:
                with patch("services.otp_service._otp_store.can_resend", return_value=(True, 0)):
                    with patch("services.otp_service._otp_store.save"):
                        success, msg, meta = OTPService.send_otp("learner@example.com", "email", purpose="login")
                        # 1. Delivery is not falsely claimed to be confirmed
                        self.assertFalse(success)
                        # 2. Ambiguity metadata is recorded
                        self.assertTrue(meta.get("ambiguous_delivery"))
                        # 3. OTP is NOT deleted from store
                        mock_delete.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_resend_provider_rejection_deletes_otp_from_store(self, mock_urlopen):
        """Verifies that explicit HTTP 403 provider rejection purges OTP from store."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://api.resend.com/emails", 403, "Forbidden", {}, None
        )

        env_vars = {
            "RESEND_API_KEY": "re_mock_key",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            with patch("services.otp_service._otp_store.delete") as mock_delete:
                with patch("services.otp_service._otp_store.can_resend", return_value=(True, 0)):
                    with patch("services.otp_service._otp_store.save"):
                        success, msg, meta = OTPService.send_otp("learner@example.com", "email", purpose="login")
                        self.assertFalse(success)
                        self.assertFalse(meta.get("ambiguous_delivery", False))
                        # Definitive provider rejection MUST purge OTP from store
                        mock_delete.assert_called_once_with("learner@example.com", purpose="login")

    @patch("urllib.request.urlopen")
    def test_resend_url_error_preserves_otp_in_store(self, mock_urlopen):
        """Verifies that socket URLError disconnect marks delivery ambiguous and preserves OTP."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection reset by peer")

        env_vars = {
            "RESEND_API_KEY": "re_mock_key",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            with patch("services.otp_service._otp_store.delete") as mock_delete:
                with patch("services.otp_service._otp_store.can_resend", return_value=(True, 0)):
                    with patch("services.otp_service._otp_store.save"):
                        success, msg, meta = OTPService.send_otp("learner@example.com", "email", purpose="login")
                        self.assertFalse(success)
                        self.assertTrue(meta.get("ambiguous_delivery"))
                        mock_delete.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_resend_ambiguous_outcome_allows_successful_subsequent_verification(self, mock_urlopen):
        """Verifies that if delivery times out but email reached user, the received code verifies successfully."""
        mock_urlopen.side_effect = TimeoutError("The read operation timed out")

        target = "timeoutlearner@example.com"
        env_vars = {
            "RESEND_API_KEY": "re_mock_key",
            "ALLOW_MOCK_OTP": "false",
            "TESTING": "true"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            # 1. Dispatch encounters read timeout
            success, msg, meta = OTPService.send_otp(target, "email", purpose="login")
            self.assertFalse(success)
            self.assertTrue(meta.get("ambiguous_delivery"))
            from services.otp_service import _otp_store
            record = _otp_store.get(target, purpose="login")
            self.assertIsNotNone(record)
            code = record["otp"]

            # 2. User enters the delivered code; verification must succeed!
            ok, v_msg = OTPService.verify_otp(target, "email", code, purpose="login")
            self.assertTrue(ok)
            self.assertEqual(v_msg, "Code verified successfully.")

    @patch("urllib.request.urlopen")
    def test_resend_dns_failure_purges_otp_from_store(self, mock_urlopen):
        """Verifies that pre-connection DNS resolution failure is classified as non-ambiguous and purges OTP."""
        import socket
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError(socket.gaierror(-2, "Name or service not known"))

        env_vars = {
            "RESEND_API_KEY": "re_mock_key",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            with patch("services.otp_service._otp_store.delete") as mock_delete:
                with patch("services.otp_service._otp_store.can_resend", return_value=(True, 0)):
                    with patch("services.otp_service._otp_store.save"):
                        success, msg, meta = OTPService.send_otp("dnsfail@example.com", "email", purpose="login")
                        self.assertFalse(success)
                        self.assertFalse(meta.get("ambiguous_delivery", False))
                        mock_delete.assert_called_once_with("dnsfail@example.com", purpose="login")

    @patch("urllib.request.urlopen")
    def test_resend_connection_refused_purges_otp_from_store(self, mock_urlopen):
        """Verifies that pre-connection TCP connection refused is classified as non-ambiguous and purges OTP."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

        env_vars = {
            "RESEND_API_KEY": "re_mock_key",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            with patch("services.otp_service._otp_store.delete") as mock_delete:
                with patch("services.otp_service._otp_store.can_resend", return_value=(True, 0)):
                    with patch("services.otp_service._otp_store.save"):
                        success, msg, meta = OTPService.send_otp("connrefused@example.com", "email", purpose="login")
                        self.assertFalse(success)
                        self.assertFalse(meta.get("ambiguous_delivery", False))
                        mock_delete.assert_called_once_with("connrefused@example.com", purpose="login")

    @patch("services.otp_service.OTPProvider.send_sms")
    def test_sms_provider_success_return_behavior(self, mock_send_sms):
        """Verifies standard 2-tuple return compatibility and persistence when SMS provider succeeds."""
        mock_send_sms.return_value = (True, "SMS sent successfully.")

        env_vars = {
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            with patch("services.otp_service._otp_store.delete") as mock_delete:
                with patch("services.otp_service._otp_store.can_resend", return_value=(True, 0)):
                    with patch("services.otp_service._otp_store.save"):
                        success, msg, meta = OTPService.send_otp("+1234567890", "phone", purpose="login")
                        self.assertTrue(success)
                        self.assertEqual(meta.get("provider_status"), "SMS sent successfully.")
                        mock_delete.assert_not_called()

    @patch("services.otp_service.OTPProvider.send_sms")
    def test_sms_provider_failure_purges_otp_from_store(self, mock_send_sms):
        """Verifies standard 2-tuple return compatibility and OTP cleanup when SMS provider fails."""
        mock_send_sms.return_value = (False, "SMS service is not configured.")

        env_vars = {
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            with patch("services.otp_service._otp_store.delete") as mock_delete:
                with patch("services.otp_service._otp_store.can_resend", return_value=(True, 0)):
                    with patch("services.otp_service._otp_store.save"):
                        success, msg, meta = OTPService.send_otp("+1234567890", "phone", purpose="login")
                        self.assertFalse(success)
                        self.assertFalse(meta.get("ambiguous_delivery", False))
                        mock_delete.assert_called_once_with("+1234567890", purpose="login")

    # --- 8. Twilio Verify REST SMS Provider Tests (Standard urllib.request) ---
    @patch("urllib.request.urlopen")
    def test_send_sms_verify_success(self, mock_urlopen):
        """Verifies successful SMS dispatch via standard urllib.request to Twilio Verify Verifications API."""
        mock_resp = MagicMock()
        mock_resp.status = 201
        mock_resp.read.return_value = b'{"sid": "VE_mock_verify_sid", "status": "pending"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        env_vars = {
            "TWILIO_ACCOUNT_SID": "AC_mock_account_sid_12345",
            "TWILIO_AUTH_TOKEN": "mock_auth_token_67890",
            "TWILIO_VERIFY_SERVICE_SID": "VA_mock_service_sid_12345",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.send_sms("+1234567890")
            self.assertTrue(success)
            self.assertEqual(msg, "SMS sent successfully.")

            # Validate request configuration
            self.assertEqual(mock_urlopen.call_count, 1)
            req = mock_urlopen.call_args[0][0]
            self.assertEqual(
                req.full_url,
                "https://verify.twilio.com/v2/Services/VA_mock_service_sid_12345/Verifications"
            )
            self.assertEqual(req.get_method(), "POST")
            self.assertTrue(req.headers.get("Authorization", "").startswith("Basic "))
            self.assertEqual(req.headers.get("Content-type"), "application/x-www-form-urlencoded")
            payload = req.data.decode("utf-8")
            self.assertIn("To=%2B1234567890", payload)
            self.assertIn("Channel=sms", payload)

    def test_send_sms_verify_missing_config_in_production(self):
        """Verifies that missing Twilio Verify configuration in production returns configuration error."""
        env_vars = {
            "TWILIO_ACCOUNT_SID": "",
            "TWILIO_AUTH_TOKEN": "",
            "TWILIO_VERIFY_SERVICE_SID": "",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production",
            "TESTING": "",
            "YUKTI_TEST_MODE": ""
        }
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.send_sms("+1234567890")
            self.assertFalse(success)
            self.assertEqual(msg, "SMS service is not configured. Please contact support.")

    def test_mock_otp_strictly_disallowed_in_production_even_if_allow_mock_true(self):
        """Verifies that production strictly disables mock OTP even when ALLOW_MOCK_OTP is set to 'true'."""
        env_vars = {
            "TWILIO_ACCOUNT_SID": "",
            "TWILIO_AUTH_TOKEN": "",
            "TWILIO_VERIFY_SERVICE_SID": "",
            "RESEND_API_KEY": "",
            "SMTP_HOST": "",
            "ALLOW_MOCK_OTP": "true",
            "FLASK_ENV": "production",
            "TESTING": "",
            "YUKTI_TEST_MODE": ""
        }
        with patch.dict(os.environ, env_vars, clear=False):
            self.assertFalse(OTPProvider._is_mock_allowed())
            success_sms, msg_sms = OTPProvider.send_sms("+1234567890")
            self.assertFalse(success_sms)
            self.assertEqual(msg_sms, "SMS service is not configured. Please contact support.")
            success_email, msg_email = OTPProvider.send_email("test@example.com", "123456")
            self.assertFalse(success_email)
            self.assertEqual(msg_email, "Email service is not configured. Please contact support.")

    @patch("urllib.request.urlopen")
    def test_send_sms_verify_unverified_recipient_error_21608(self, mock_urlopen):
        """Verifies that Twilio Error 21608 (trial unverified recipient) returns safe, specific error message."""
        import io
        import urllib.error
        err_body = b'{"code": 21608, "message": "The number is unverified. Trial accounts cannot send messages to unverified numbers."}'
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://verify.twilio.com", 400, "Bad Request", {}, io.BytesIO(err_body)
        )

        env_vars = {
            "TWILIO_ACCOUNT_SID": "AC_mock_sid",
            "TWILIO_AUTH_TOKEN": "mock_token",
            "TWILIO_VERIFY_SERVICE_SID": "VA_mock_service_sid",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.send_sms("+19999999999")
            self.assertFalse(success)
            self.assertIn("unverified on the SMS service", msg)
            self.assertNotIn("21608", msg)  # Raw provider error codes never leaked to user

    @patch("urllib.request.urlopen")
    def test_send_sms_verify_auth_error_401(self, mock_urlopen):
        """Verifies that Twilio HTTP 401 returns clean authentication error message."""
        import io
        import urllib.error
        err_body = b'{"code": 20003, "message": "Authenticate"}'
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://verify.twilio.com", 401, "Unauthorized", {}, io.BytesIO(err_body)
        )

        env_vars = {
            "TWILIO_ACCOUNT_SID": "AC_mock_sid",
            "TWILIO_AUTH_TOKEN": "invalid_token",
            "TWILIO_VERIFY_SERVICE_SID": "VA_mock_service_sid",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.send_sms("+1234567890")
            self.assertFalse(success)
            self.assertEqual(msg, "SMS service authentication error. Please contact support.")

    @patch("urllib.request.urlopen")
    def test_send_sms_verify_rate_limit_60203(self, mock_urlopen):
        """Verifies that Twilio Verify code 60203 returns clean rate limit message."""
        import io
        import urllib.error
        err_body = b'{"code": 60203, "message": "Max send attempts reached"}'
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://verify.twilio.com", 429, "Too Many Requests", {}, io.BytesIO(err_body)
        )

        env_vars = {
            "TWILIO_ACCOUNT_SID": "AC_mock_sid",
            "TWILIO_AUTH_TOKEN": "mock_token",
            "TWILIO_VERIFY_SERVICE_SID": "VA_mock_service_sid",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.send_sms("+1234567890")
            self.assertFalse(success)
            self.assertEqual(msg, "Too many verification attempts for this phone number. Please try again later.")

    @patch("urllib.request.urlopen")
    def test_send_sms_verify_network_error(self, mock_urlopen):
        """Verifies that DNS/network errors return safe failure message."""
        import socket
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError(socket.gaierror(-2, "Name or service not known"))

        env_vars = {
            "TWILIO_ACCOUNT_SID": "AC_mock_sid",
            "TWILIO_AUTH_TOKEN": "mock_token",
            "TWILIO_VERIFY_SERVICE_SID": "VA_mock_service_sid",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.send_sms("+1234567890")
            self.assertFalse(success)
            self.assertEqual(msg, "Failed to send verification SMS. Please try again later.")

    @patch("urllib.request.urlopen")
    def test_send_sms_verify_timeout(self, mock_urlopen):
        """Verifies that socket timeouts return safe failure message."""
        mock_urlopen.side_effect = TimeoutError("The read operation timed out")

        env_vars = {
            "TWILIO_ACCOUNT_SID": "AC_mock_sid",
            "TWILIO_AUTH_TOKEN": "mock_token",
            "TWILIO_VERIFY_SERVICE_SID": "VA_mock_service_sid",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.send_sms("+1234567890")
            self.assertFalse(success)
            self.assertEqual(msg, "Failed to send verification SMS. Please try again later.")

    # --- Twilio Verify Check Tests ---
    @patch("urllib.request.urlopen")
    def test_check_sms_verify_approved(self, mock_urlopen):
        """Verifies successful code check via Twilio Verify VerificationCheck API."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"sid": "VE_mock_sid", "status": "approved", "valid": true}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        env_vars = {
            "TWILIO_ACCOUNT_SID": "AC_mock_sid",
            "TWILIO_AUTH_TOKEN": "mock_token",
            "TWILIO_VERIFY_SERVICE_SID": "VA_mock_service_sid",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.check_sms("+1234567890", "654321")
            self.assertTrue(success)
            self.assertEqual(msg, "Code verified successfully.")

            req = mock_urlopen.call_args[0][0]
            self.assertEqual(
                req.full_url,
                "https://verify.twilio.com/v2/Services/VA_mock_service_sid/VerificationCheck"
            )
            payload = req.data.decode("utf-8")
            self.assertIn("To=%2B1234567890", payload)
            self.assertIn("Code=654321", payload)

    @patch("urllib.request.urlopen")
    def test_check_sms_verify_wrong_code_pending(self, mock_urlopen):
        """Verifies that an incorrect code returning pending status is treated as invalid."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"sid": "VE_mock_sid", "status": "pending", "valid": false}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        env_vars = {
            "TWILIO_ACCOUNT_SID": "AC_mock_sid",
            "TWILIO_AUTH_TOKEN": "mock_token",
            "TWILIO_VERIFY_SERVICE_SID": "VA_mock_service_sid",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.check_sms("+1234567890", "000000")
            self.assertFalse(success)
            self.assertIn("Invalid verification code", msg)

    @patch("urllib.request.urlopen")
    def test_check_sms_verify_expired_or_not_found_404(self, mock_urlopen):
        """Verifies that HTTP 404 from VerificationCheck is reported as expired code."""
        import io
        import urllib.error
        err_body = b'{"code": 20404, "message": "The requested resource was not found"}'
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://verify.twilio.com", 404, "Not Found", {}, io.BytesIO(err_body)
        )

        env_vars = {
            "TWILIO_ACCOUNT_SID": "AC_mock_sid",
            "TWILIO_AUTH_TOKEN": "mock_token",
            "TWILIO_VERIFY_SERVICE_SID": "VA_mock_service_sid",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.check_sms("+1234567890", "123456")
            self.assertFalse(success)
            self.assertIn("expired or was not requested", msg)

    @patch("urllib.request.urlopen")
    def test_check_sms_verify_max_attempts_reached_60202(self, mock_urlopen):
        """Verifies that Twilio code 60202 invalidates the code due to too many failed attempts."""
        import io
        import urllib.error
        err_body = b'{"code": 60202, "message": "Max check attempts reached"}'
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://verify.twilio.com", 400, "Bad Request", {}, io.BytesIO(err_body)
        )

        env_vars = {
            "TWILIO_ACCOUNT_SID": "AC_mock_sid",
            "TWILIO_AUTH_TOKEN": "mock_token",
            "TWILIO_VERIFY_SERVICE_SID": "VA_mock_service_sid",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "production"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            success, msg = OTPProvider.check_sms("+1234567890", "123456")
            self.assertFalse(success)
            self.assertIn("Too many failed attempts", msg)

    # --- End-to-End Phone OTP via Twilio Verify ---
    @patch("services.otp_service.is_production", return_value=False)
    @patch("urllib.request.urlopen")
    def test_otp_service_phone_verify_end_to_end_flow(self, mock_urlopen, mock_prod):
        """Verifies full end-to-end phone OTP flow: send verification, purpose isolation, and check verification."""
        # 1. Send verification (Twilio Verifications endpoint)
        mock_resp_send = MagicMock()
        mock_resp_send.status = 201
        mock_resp_send.read.return_value = b'{"sid": "VE_test_send_sid", "status": "pending"}'

        mock_urlopen.return_value.__enter__.return_value = mock_resp_send

        target_phone = "+15551234567"
        env_vars = {
            "TWILIO_ACCOUNT_SID": "AC_e2e_sid",
            "TWILIO_AUTH_TOKEN": "e2e_token",
            "TWILIO_VERIFY_SERVICE_SID": "VA_e2e_verify_sid",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "testing"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            send_ok, send_msg, meta = OTPService.send_otp(target_phone, "phone", purpose="login")
            self.assertTrue(send_ok)
            self.assertEqual(meta["target"], "+15****67")

            # 2. Strict Purpose Isolation: Attempting to verify for "password_reset" MUST fail!
            wrong_purpose_ok, wrong_purpose_msg = OTPService.verify_otp(
                target_phone, "phone", "123456", purpose="password_reset"
            )
            self.assertFalse(wrong_purpose_ok)
            self.assertIn("expired or was not requested", wrong_purpose_msg)

            # 3. Check verification for correct purpose "login" (Twilio VerificationCheck endpoint)
            mock_resp_check = MagicMock()
            mock_resp_check.status = 200
            mock_resp_check.read.return_value = b'{"sid": "VE_test_send_sid", "status": "approved", "valid": true}'
            mock_urlopen.return_value.__enter__.return_value = mock_resp_check

            verify_ok, verify_msg = OTPService.verify_otp(target_phone, "phone", "123456", purpose="login")
            self.assertTrue(verify_ok)
            self.assertEqual(verify_msg, "Code verified successfully.")

            # 4. Single-use consumption: Attempting to verify again MUST fail
            second_verify_ok, second_verify_msg = OTPService.verify_otp(target_phone, "phone", "123456", purpose="login")
            self.assertFalse(second_verify_ok)
            self.assertIn("expired or was not requested", second_verify_msg)

    @patch("services.otp_service.is_production", return_value=False)
    @patch("urllib.request.urlopen")
    def test_otp_service_phone_verify_attempt_lockout(self, mock_urlopen, mock_prod):
        """Verifies that consecutive wrong verification checks track attempts and invalidate the record."""
        # 1. Send verification
        mock_resp_send = MagicMock()
        mock_resp_send.status = 201
        mock_resp_send.read.return_value = b'{"sid": "VE_test_send_sid", "status": "pending"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp_send

        target_phone = "+15559876543"
        env_vars = {
            "TWILIO_ACCOUNT_SID": "AC_lockout_sid",
            "TWILIO_AUTH_TOKEN": "lockout_token",
            "TWILIO_VERIFY_SERVICE_SID": "VA_lockout_verify_sid",
            "ALLOW_MOCK_OTP": "false",
            "FLASK_ENV": "testing"
        }
        with patch.dict(os.environ, env_vars, clear=False):
            send_ok, _, _ = OTPService.send_otp(target_phone, "phone", purpose="login")
            self.assertTrue(send_ok)

            # 2. Check returns pending (wrong code)
            mock_resp_pending = MagicMock()
            mock_resp_pending.status = 200
            mock_resp_pending.read.return_value = b'{"sid": "VE_test_send_sid", "status": "pending", "valid": false}'
            mock_urlopen.return_value.__enter__.return_value = mock_resp_pending

            # Attempt 1
            ok1, msg1 = OTPService.verify_otp(target_phone, "phone", "000001", purpose="login")
            self.assertFalse(ok1)
            self.assertIn("2 attempt(s) remaining", msg1)

            # Attempt 2
            ok2, msg2 = OTPService.verify_otp(target_phone, "phone", "000002", purpose="login")
            self.assertFalse(ok2)
            self.assertIn("1 attempt(s) remaining", msg2)

            # Attempt 3 -> Invalidated
            ok3, msg3 = OTPService.verify_otp(target_phone, "phone", "000003", purpose="login")
            self.assertFalse(ok3)
            self.assertIn("invalidated", msg3.lower())

            # Attempt 4 -> Expired / not requested
            ok4, msg4 = OTPService.verify_otp(target_phone, "phone", "000004", purpose="login")
            self.assertFalse(ok4)
            self.assertIn("expired", msg4.lower())


if __name__ == "__main__":
    unittest.main()

