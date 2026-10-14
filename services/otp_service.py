import os
import re
import time
import hmac
import json
import secrets
import logging
import threading
from typing import Tuple, Dict, Any

logger = logging.getLogger(__name__)

# Regex for validation
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
PHONE_REGEX = re.compile(r"^\+?[1-9]\d{7,14}$")


def mask_target(target: str) -> str:
    """Mask email or phone number for safe diagnostic logging."""
    if not target:
        return "****"
    if "@" in target:
        parts = target.split("@")
        name = parts[0]
        domain = parts[1]
        masked_name = name[:2] + "***" if len(name) > 2 else name[:1] + "***"
        return f"{masked_name}@{domain}"
    if len(target) > 5:
        return f"{target[:3]}****{target[-2:]}"
    return "****"


def is_production() -> bool:
    env = os.getenv("FLASK_ENV", "").lower()
    prod = os.getenv("PRODUCTION", "").lower()
    render = os.getenv("RENDER", "").lower()
    return env == "production" or prod in ("true", "1") or render in ("true", "1")


class OTPStorageError(RuntimeError):
    """Raised when shared OTP storage fails in production."""
    pass


class OTPStore:
    """
    OTP Store with Redis backing for multi-worker production deployments
    and safe thread-safe in-memory fallback for local development/testing.
    Supports strict cryptographic purpose isolation (login, password_reset, username_recovery).
    In production mode, Redis failures fail-safe with OTPStorageError instead of
    falling back silently to multi-worker desynchronized memory.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._memory: Dict[str, Dict[str, Any]] = {}
        self._reset_tokens: Dict[str, Dict[str, Any]] = {}
        self._ip_tracker: Dict[str, list] = {}
        self._redis_client = None
        self._use_redis = False
        self._init_redis()

    def _init_redis(self):
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            try:
                import redis
                client = redis.Redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=1,
                    socket_timeout=2
                )
                client.ping()
                self._redis_client = client
                self._use_redis = True
                logger.info("OTPStore initialized with shared Redis backend.")
            except Exception as e:
                self._use_redis = False
                if is_production():
                    logger.critical(f"OTPStore Redis connection failed in production: {e}")
                else:
                    logger.warning(f"OTPStore Redis connection unavailable ({e}); using thread-safe in-memory store.")
        else:
            if is_production():
                logger.critical("REDIS_URL is not set in production. Shared multi-worker store unavailable.")

    def _store_key(self, purpose: str, target: str) -> str:
        return f"{purpose}:{target}"

    def save(self, target: str, otp: str, ttl_seconds: int = 300, purpose: str = "login") -> None:
        if is_production() and not (self._use_redis and self._redis_client):
            raise OTPStorageError("Shared Redis backend required in production is unavailable.")

        now = time.time()
        record_data = {
            "otp": otp,
            "purpose": purpose,
            "expires_at": now + ttl_seconds,
            "attempts": 0,
            "last_sent": now
        }

        if self._use_redis and self._redis_client:
            try:
                key = f"yukti:otp:{purpose}:{target}"
                self._redis_client.setex(key, ttl_seconds, json.dumps(record_data))
                cooldown_key = f"yukti:otp:cooldown:{purpose}:{target}"
                self._redis_client.setex(cooldown_key, 60, str(now))
                return
            except Exception as e:
                if is_production():
                    raise OTPStorageError(f"Redis write failed in production: {e}")
                logger.warning(f"Redis write failed ({e}); falling back to memory.")

        with self._lock:
            self._memory[self._store_key(purpose, target)] = record_data

    def get(self, target: str, purpose: str = "login") -> Dict[str, Any] | None:
        if is_production() and not (self._use_redis and self._redis_client):
            raise OTPStorageError("Shared Redis backend required in production is unavailable.")

        if self._use_redis and self._redis_client:
            try:
                key = f"yukti:otp:{purpose}:{target}"
                val = self._redis_client.get(key)
                if not val:
                    return None
                data = json.loads(val)
                if time.time() > data.get("expires_at", 0):
                    self._redis_client.delete(key)
                    return None
                if data.get("purpose") != purpose:
                    return None
                return data
            except Exception as e:
                if is_production():
                    raise OTPStorageError(f"Redis get failed in production: {e}")
                logger.warning(f"Redis get failed ({e}); falling back to memory.")

        with self._lock:
            k = self._store_key(purpose, target)
            record = self._memory.get(k)
            if not record:
                return None
            if time.time() > record["expires_at"]:
                self._memory.pop(k, None)
                return None
            if record.get("purpose") != purpose:
                return None
            return record

    def increment_attempts(self, target: str, purpose: str = "login") -> int:
        if is_production() and not (self._use_redis and self._redis_client):
            raise OTPStorageError("Shared Redis backend required in production is unavailable.")

        if self._use_redis and self._redis_client:
            try:
                key = f"yukti:otp:{purpose}:{target}"
                val = self._redis_client.get(key)
                if not val:
                    return 0
                data = json.loads(val)
                data["attempts"] = data.get("attempts", 0) + 1
                ttl = self._redis_client.ttl(key)
                if ttl and ttl > 0:
                    self._redis_client.setex(key, ttl, json.dumps(data))
                else:
                    self._redis_client.set(key, json.dumps(data))
                return data["attempts"]
            except Exception as e:
                if is_production():
                    raise OTPStorageError(f"Redis increment failed in production: {e}")
                logger.warning(f"Redis increment failed ({e}); falling back to memory.")

        with self._lock:
            k = self._store_key(purpose, target)
            record = self._memory.get(k)
            if record:
                record["attempts"] += 1
                return record["attempts"]
            return 0

    def delete(self, target: str, purpose: str = "login") -> None:
        if is_production() and not (self._use_redis and self._redis_client):
            raise OTPStorageError("Shared Redis backend required in production is unavailable.")

        if self._use_redis and self._redis_client:
            try:
                key = f"yukti:otp:{purpose}:{target}"
                self._redis_client.delete(key)
                return
            except Exception as e:
                if is_production():
                    raise OTPStorageError(f"Redis delete failed in production: {e}")
                logger.warning(f"Redis delete failed ({e})")

        with self._lock:
            self._memory.pop(self._store_key(purpose, target), None)

    def can_resend(self, target: str, cooldown_seconds: int = 60, purpose: str = "login") -> Tuple[bool, int]:
        if is_production() and not (self._use_redis and self._redis_client):
            raise OTPStorageError("Shared Redis backend required in production is unavailable.")

        if self._use_redis and self._redis_client:
            try:
                cooldown_key = f"yukti:otp:cooldown:{purpose}:{target}"
                last_sent_val = self._redis_client.get(cooldown_key)
                if last_sent_val:
                    last_sent = float(last_sent_val)
                    elapsed = time.time() - last_sent
                    if elapsed < cooldown_seconds:
                        return False, max(1, int(cooldown_seconds - elapsed))
                    return True, 0
                return True, 0
            except Exception as e:
                if is_production():
                    raise OTPStorageError(f"Redis cooldown check failed in production: {e}")
                logger.warning(f"Redis cooldown check failed ({e})")

        with self._lock:
            record = self._memory.get(self._store_key(purpose, target))
            if not record:
                return True, 0
            elapsed = time.time() - record.get("last_sent", 0)
            if elapsed < cooldown_seconds:
                return False, max(1, int(cooldown_seconds - elapsed))
            return True, 0

    def check_ip_rate_limit(self, ip: str, max_requests: int = 20, window_seconds: int = 3600) -> Tuple[bool, int]:
        if not ip:
            return True, 0
        if not is_production() and ip in ("127.0.0.1", "localhost", "::1"):
            return True, 0

        if is_production() and not (self._use_redis and self._redis_client):
            raise OTPStorageError("Shared Redis backend required in production is unavailable.")

        if self._use_redis and self._redis_client:
            try:
                key = f"yukti:otp:ip:{ip}"
                current = self._redis_client.incr(key)
                if current == 1:
                    self._redis_client.expire(key, window_seconds)
                if current > max_requests:
                    ttl = self._redis_client.ttl(key)
                    return False, max(1, ttl)
                return True, 0
            except Exception as e:
                if is_production():
                    raise OTPStorageError(f"Redis IP rate limit check failed in production: {e}")
                logger.warning(f"Redis IP rate limit check failed ({e})")

        now = time.time()
        with self._lock:
            history = self._ip_tracker.get(ip, [])
            history = [t for t in history if now - t < window_seconds]
            if len(history) >= max_requests:
                retry_after = int(window_seconds - (now - history[0]))
                self._ip_tracker[ip] = history
                return False, max(1, retry_after)
            history.append(now)
            self._ip_tracker[ip] = history
            return True, 0

    def record_cooldown(self, target: str, cooldown_seconds: int = 60, purpose: str = "login") -> None:
        """Record a cooldown timestamp for a target without generating an OTP (mitigates account enumeration)."""
        if is_production() and not (self._use_redis and self._redis_client):
            raise OTPStorageError("Shared Redis backend required in production is unavailable.")

        now = time.time()
        if self._use_redis and self._redis_client:
            try:
                cooldown_key = f"yukti:otp:cooldown:{purpose}:{target}"
                self._redis_client.setex(cooldown_key, cooldown_seconds, str(now))
                return
            except Exception as e:
                if is_production():
                    raise OTPStorageError(f"Redis record_cooldown failed in production: {e}")
                logger.warning(f"Redis record_cooldown failed ({e})")

        with self._lock:
            k = self._store_key(purpose, target)
            record = self._memory.get(k)
            if record:
                record["last_sent"] = now
            else:
                self._memory[k] = {
                    "otp": "",
                    "purpose": purpose,
                    "expires_at": now + cooldown_seconds,
                    "attempts": 0,
                    "last_sent": now
                }

    def verify_and_consume(self, target: str, otp: str, purpose: str = "login") -> Tuple[bool, str, int]:
        """
        Atomically verify, track attempts, and consume an OTP.
        Guarantees single-use semantics across concurrent workers without TOCTOU races.
        Returns: (success: bool, status: str ("success" | "wrong_code" | "invalidated" | "expired"), remaining_attempts: int)
        """
        if is_production() and not (self._use_redis and self._redis_client):
            raise OTPStorageError("Shared Redis backend required in production is unavailable.")

        if self._use_redis and self._redis_client:
            try:
                key = f"yukti:otp:{purpose}:{target}"
                lua_script = """
                local key = KEYS[1]
                local cand = tostring(ARGV[1])
                local now = tonumber(ARGV[2])
                local purp = ARGV[3]

                local val = redis.call('GET', key)
                if not val then
                    return cjson.encode({status = "expired", remaining = 0})
                end

                local rec = cjson.decode(val)
                if now > (rec.expires_at or 0) then
                    redis.call('DEL', key)
                    return cjson.encode({status = "expired", remaining = 0})
                end

                if rec.purpose ~= purp then
                    return cjson.encode({status = "expired", remaining = 0})
                end

                rec.attempts = (rec.attempts or 0) + 1

                if tostring(rec.otp) == cand then
                    redis.call('DEL', key)
                    return cjson.encode({status = "success", remaining = 0})
                end

                if rec.attempts >= 3 then
                    redis.call('DEL', key)
                    return cjson.encode({status = "invalidated", remaining = 0})
                else
                    local ttl = redis.call('TTL', key)
                    if ttl and ttl > 0 then
                        redis.call('SETEX', key, ttl, cjson.encode(rec))
                    else
                        redis.call('SET', key, cjson.encode(rec))
                    end
                    return cjson.encode({status = "wrong_code", remaining = (3 - rec.attempts)})
                end
                """
                res = self._redis_client.eval(lua_script, 1, key, str(otp).strip(), time.time(), purpose)
                if not res:
                    return False, "expired", 0
                data = json.loads(res)
                st = data.get("status", "expired")
                rem = data.get("remaining", 0)
                return (st == "success"), st, rem
            except Exception as e:
                if is_production():
                    raise OTPStorageError(f"Redis verify_and_consume failed in production: {e}")
                logger.warning(f"Redis verify_and_consume failed ({e}); falling back to memory.")

        with self._lock:
            k = self._store_key(purpose, target)
            rec = self._memory.get(k)
            if not rec:
                return False, "expired", 0
            if time.time() > rec.get("expires_at", 0):
                self._memory.pop(k, None)
                return False, "expired", 0
            if rec.get("purpose") != purpose:
                return False, "expired", 0

            rec["attempts"] = rec.get("attempts", 0) + 1
            if hmac.compare_digest(str(rec.get("otp", "")).strip(), str(otp).strip()):
                self._memory.pop(k, None)
                return True, "success", 0

            if rec["attempts"] >= 3:
                self._memory.pop(k, None)
                return False, "invalidated", 0

            return False, "wrong_code", 3 - rec["attempts"]

    # Password Reset Authorizations
    def save_reset_token(self, token: str, user_id: int, target: str, ttl_seconds: int = 600) -> None:
        if is_production() and not (self._use_redis and self._redis_client):
            raise OTPStorageError("Shared Redis backend required in production is unavailable.")

        now = time.time()
        record_data = {
            "user_id": user_id,
            "target": target,
            "expires_at": now + ttl_seconds
        }
        if self._use_redis and self._redis_client:
            try:
                key = f"yukti:reset_token:{token}"
                self._redis_client.setex(key, ttl_seconds, json.dumps(record_data))
                return
            except Exception as e:
                if is_production():
                    raise OTPStorageError(f"Redis save_reset_token failed in production: {e}")
                logger.warning(f"Redis save_reset_token failed ({e}); saving to memory.")

        with self._lock:
            self._reset_tokens[token] = record_data

    def get_reset_token(self, token: str) -> Dict[str, Any] | None:
        if is_production() and not (self._use_redis and self._redis_client):
            raise OTPStorageError("Shared Redis backend required in production is unavailable.")

        if self._use_redis and self._redis_client:
            try:
                key = f"yukti:reset_token:{token}"
                val = self._redis_client.get(key)
                if not val:
                    return None
                data = json.loads(val)
                if time.time() > data.get("expires_at", 0):
                    self._redis_client.delete(key)
                    return None
                return data
            except Exception as e:
                if is_production():
                    raise OTPStorageError(f"Redis get_reset_token failed in production: {e}")
                logger.warning(f"Redis get_reset_token failed ({e}); reading from memory.")

        with self._lock:
            record = self._reset_tokens.get(token)
            if not record:
                return None
            if time.time() > record["expires_at"]:
                self._reset_tokens.pop(token, None)
                return None
            return record

    def delete_reset_token(self, token: str) -> None:
        if is_production() and not (self._use_redis and self._redis_client):
            raise OTPStorageError("Shared Redis backend required in production is unavailable.")

        if self._use_redis and self._redis_client:
            try:
                key = f"yukti:reset_token:{token}"
                self._redis_client.delete(key)
                return
            except Exception as e:
                if is_production():
                    raise OTPStorageError(f"Redis delete_reset_token failed in production: {e}")
                logger.warning(f"Redis delete_reset_token failed ({e})")

        with self._lock:
            self._reset_tokens.pop(token, None)

    def consume_reset_token(self, token: str) -> Dict[str, Any] | None:
        """
        Atomically fetch and remove a password reset authorization token.
        Prevents TOCTOU race conditions where concurrent requests could reuse the same token.
        """
        if is_production() and not (self._use_redis and self._redis_client):
            raise OTPStorageError("Shared Redis backend required in production is unavailable.")

        if self._use_redis and self._redis_client:
            try:
                key = f"yukti:reset_token:{token}"
                lua_script = """
                local val = redis.call('GET', KEYS[1])
                if val then
                    redis.call('DEL', KEYS[1])
                    return val
                else
                    return nil
                end
                """
                val = self._redis_client.eval(lua_script, 1, key)
                if not val:
                    return None
                data = json.loads(val)
                if time.time() > data.get("expires_at", 0):
                    return None
                return data
            except Exception as e:
                if is_production():
                    raise OTPStorageError(f"Redis consume_reset_token failed in production: {e}")
                logger.warning(f"Redis consume_reset_token failed ({e}); reading from memory.")

        with self._lock:
            record = self._reset_tokens.pop(token, None)
            if not record:
                return None
            if time.time() > record.get("expires_at", 0):
                return None
            return record


_otp_store = OTPStore()


class OTPProvider:
    """Pluggable provider for Email and SMS OTP dispatch with secure production fallbacks."""

    @staticmethod
    def _is_mock_allowed() -> bool:
        return (
            os.getenv("ALLOW_MOCK_OTP", "").lower() in ("true", "1")
            or os.getenv("TESTING") == "true"
            or os.getenv("FLASK_ENV") == "development"
            or os.getenv("YUKTI_TEST_MODE") == "1"
        )

    @staticmethod
    def send_email(email: str, otp: str, purpose: str = "login") -> Tuple[bool, str]:
        resend_api_key = os.getenv("RESEND_API_KEY")
        resend_from = os.getenv("RESEND_FROM", "Yukti <onboarding@resend.dev>")

        smtp_host = os.getenv("SMTP_HOST")
        smtp_port = os.getenv("SMTP_PORT")
        smtp_user = os.getenv("SMTP_USER")
        smtp_pass = os.getenv("SMTP_PASS")

        if purpose == "password_reset":
            subject = "Yukti Password Reset Code"
            body_text = f"Your Yukti password reset code is: {otp}\nValid for 5 minutes. If you did not request a password reset, please ignore this email."
        elif purpose == "username_recovery":
            subject = "Yukti Username Recovery Code"
            body_text = f"Your Yukti username recovery code is: {otp}\nValid for 5 minutes. If you did not request username recovery, please ignore this email."
        else:
            subject = "Yukti Verification Code"
            body_text = f"Your Yukti verification code is: {otp}\nValid for 5 minutes."

        # 1. Primary HTTPS Provider: Resend API (Preferred for cloud containers)
        if resend_api_key:
            try:
                import json
                import urllib.request
                import urllib.error

                payload = json.dumps({
                    "from": resend_from,
                    "to": [email],
                    "subject": subject,
                    "text": body_text
                }).encode("utf-8")

                req = urllib.request.Request(
                    "https://api.resend.com/emails",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {resend_api_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "Yukti/1.0"
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status in (200, 201):
                        logger.info(f"Dispatched {purpose} email OTP to {mask_target(email)} via Resend HTTPS API.")
                        return True, "Email sent successfully."
                    logger.error(f"Resend API returned unexpected status code: {resp.status}")
                    return False, "Failed to send verification email. Please try again later."
            except urllib.error.HTTPError as e:
                logger.error(f"Resend API HTTP error: {e.code} {e.reason}")
                return False, "Failed to send verification email. Please try again later."
            except Exception as e:
                logger.error(f"Failed to send email OTP via Resend: {type(e).__name__}")
                return False, "Failed to send verification email. Please try again later."

        # 2. Secondary Provider: SMTP (used only when RESEND_API_KEY is absent)
        if smtp_host and smtp_user and smtp_pass:
            try:
                import smtplib
                from email.mime.text import MIMEText
                port = int(smtp_port or 587)
                msg = MIMEText(body_text)
                msg["Subject"] = subject
                msg["From"] = smtp_user
                msg["To"] = email

                with smtplib.SMTP(smtp_host, port, timeout=10) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
                logger.info(f"Dispatched {purpose} email OTP to {mask_target(email)} via SMTP provider.")
                return True, "Email sent successfully."
            except Exception as e:
                logger.error(f"Failed to send email OTP via SMTP: {e}")
                return False, "Failed to send verification email. Please try again later."

        if not OTPProvider._is_mock_allowed():
            logger.error("Email provider not configured and mock OTP is disallowed in production.")
            return False, "Email service is not configured. Please contact support."

        # Dev / Testing / Mock fallback - never log plaintext OTP at INFO in production
        logger.info(f"[OTP DEV/MOCK] Dispatched {purpose} email OTP to {mask_target(email)}")
        if os.getenv("FLASK_ENV") == "development":
            logger.debug(f"[DEV DEBUG ONLY] Plaintext OTP: {otp}")
        return True, "Email dispatched via development/mock provider."

    @staticmethod
    def send_sms(phone: str, otp: str) -> Tuple[bool, str]:
        twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
        twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
        twilio_from = os.getenv("TWILIO_FROM_NUMBER")

        if twilio_sid and twilio_token and twilio_from:
            try:
                from twilio.rest import Client as TwilioClient
                client = TwilioClient(twilio_sid, twilio_token)
                client.messages.create(
                    body=f"Your Yukti verification code is: {otp}. Valid for 5 minutes.",
                    from_=twilio_from,
                    to=phone
                )
                logger.info(f"Dispatched SMS OTP to {mask_target(phone)} via Twilio provider.")
                return True, "SMS sent successfully."
            except Exception as e:
                logger.error(f"Failed to send SMS OTP via Twilio: {e}")
                return False, "Failed to send verification SMS. Please try again later."

        if not OTPProvider._is_mock_allowed():
            logger.error("Twilio provider not configured and mock OTP is disallowed in production.")
            return False, "SMS service is not configured. Please contact support."

        # Dev / Testing / Mock fallback - never log plaintext OTP at INFO in production
        logger.info(f"[OTP DEV/MOCK] Dispatched SMS OTP to {mask_target(phone)}")
        if os.getenv("FLASK_ENV") == "development":
            logger.debug(f"[DEV DEBUG ONLY] Plaintext OTP: {otp}")
        return True, "SMS dispatched via development/mock provider."


class OTPService:
    @staticmethod
    def normalize_target(target: str, target_type: str) -> Tuple[str, str | None]:
        target = (target or "").strip()
        if target_type == "email":
            target = target.lower()
            if not EMAIL_REGEX.match(target):
                return target, "Invalid email address format."
            return target, None
        elif target_type == "phone":
            cleaned = re.sub(r"[\s\-\(\)]", "", target)
            if not PHONE_REGEX.match(cleaned):
                return cleaned, "Invalid phone number format. Must include country code, e.g. +1234567890."
            return cleaned, None
        else:
            return target, "Unsupported OTP type. Must be 'email' or 'phone'."

    @classmethod
    def send_otp(
        cls,
        target: str,
        target_type: str,
        client_ip: str | None = None,
        purpose: str = "login"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        normalized, err = cls.normalize_target(target, target_type)
        if err:
            return False, err, {}

        try:
            # 1. IP rate limiting
            if client_ip:
                allowed_ip, ip_retry = _otp_store.check_ip_rate_limit(client_ip, max_requests=20, window_seconds=3600)
                if not allowed_ip:
                    return False, f"Too many requests from this IP. Please try again in {ip_retry} seconds.", {"retry_after": ip_retry}

            # 2. Per-target cooldown (60 seconds) bound to purpose
            can_send, wait_secs = _otp_store.can_resend(normalized, cooldown_seconds=60, purpose=purpose)
            if not can_send:
                return False, f"Please wait {wait_secs} seconds before requesting a new code.", {"retry_after": wait_secs}

            # 3. Cryptographically secure 6-digit code
            otp = f"{secrets.randbelow(900000) + 100000:06d}"
            _otp_store.save(normalized, otp, ttl_seconds=300, purpose=purpose)
        except OTPStorageError as e:
            logger.error(f"OTP storage error during send_otp: {e}")
            return False, "Authentication service is temporarily unavailable. Please try again later.", {"error": "service_unavailable"}

        # 4. Dispatch via provider
        if target_type == "email":
            success, msg = OTPProvider.send_email(normalized, otp, purpose=purpose)
        else:
            success, msg = OTPProvider.send_sms(normalized, otp)

        if not success:
            try:
                _otp_store.delete(normalized, purpose=purpose)
            except Exception:
                pass
            return False, msg, {}

        meta = {"expires_in": 300, "target": mask_target(normalized), "provider_status": msg, "purpose": purpose}
        # In automated test mode ONLY, expose code for test fixtures
        if os.getenv("TESTING") == "true" or os.getenv("YUKTI_TEST_MODE") == "1":
            meta["debug_otp"] = otp

        return True, "Verification code sent successfully.", meta

    @classmethod
    def check_ip_rate_limit(cls, ip: str, max_requests: int = 20, window_seconds: int = 3600) -> Tuple[bool, int]:
        return _otp_store.check_ip_rate_limit(ip, max_requests=max_requests, window_seconds=window_seconds)

    @classmethod
    def can_resend(cls, target: str, cooldown_seconds: int = 60, purpose: str = "login") -> Tuple[bool, int]:
        normalized, _ = cls.normalize_target(target, "email" if "@" in target else "phone")
        return _otp_store.can_resend(normalized, cooldown_seconds=cooldown_seconds, purpose=purpose)

    @classmethod
    def record_cooldown(cls, target: str, cooldown_seconds: int = 60, purpose: str = "login") -> None:
        normalized, _ = cls.normalize_target(target, "email" if "@" in target else "phone")
        _otp_store.record_cooldown(normalized, cooldown_seconds=cooldown_seconds, purpose=purpose)

    @classmethod
    def verify_otp(
        cls,
        target: str,
        target_type: str,
        otp: str,
        purpose: str = "login"
    ) -> Tuple[bool, str]:
        normalized, err = cls.normalize_target(target, target_type)
        if err:
            return False, err

        try:
            success, status, remaining = _otp_store.verify_and_consume(normalized, otp, purpose=purpose)
            if success:
                return True, "Code verified successfully."
            if status == "invalidated":
                return False, "Too many failed attempts. Code invalidated. Please request a new code."
            if status == "wrong_code":
                return False, f"Invalid verification code. {remaining} attempt(s) remaining."
            return False, "Verification code has expired or was not requested. Please request a new code."
        except OTPStorageError as e:
            logger.error(f"OTP storage error during verify_otp: {e}")
            return False, "Authentication service is temporarily unavailable. Please try again later."

    # Password Reset Authorizations
    @classmethod
    def create_password_reset_token(cls, user_id: int, target: str) -> str:
        token = secrets.token_urlsafe(32)
        _otp_store.save_reset_token(token, user_id, target, ttl_seconds=600)
        return token

    @classmethod
    def verify_password_reset_token(cls, token: str) -> Tuple[bool, str, Dict[str, Any] | None]:
        if not token:
            return False, "Reset authorization token is required.", None
        try:
            record = _otp_store.get_reset_token(token)
            if not record:
                return False, "Password reset authorization has expired or is invalid. Please request a new code.", None
            return True, "Valid reset authorization.", record
        except OTPStorageError as e:
            logger.error(f"OTP storage error during verify_password_reset_token: {e}")
            return False, "Authentication service is temporarily unavailable. Please try again later.", None

    @classmethod
    def verify_and_consume_password_reset_token(cls, token: str) -> Tuple[bool, str, Dict[str, Any] | None]:
        if not token:
            return False, "Reset authorization token is required.", None
        try:
            record = _otp_store.consume_reset_token(token)
            if not record:
                return False, "Password reset authorization has expired or has already been used.", None
            return True, "Valid reset authorization.", record
        except OTPStorageError as e:
            logger.error(f"OTP storage error during verify_and_consume_password_reset_token: {e}")
            return False, "Authentication service is temporarily unavailable. Please try again later.", None

    @classmethod
    def consume_password_reset_token(cls, token: str) -> None:
        try:
            _otp_store.delete_reset_token(token)
        except Exception:
            pass
