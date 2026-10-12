from flask import Blueprint, request, jsonify, make_response
from werkzeug.security import generate_password_hash, check_password_hash
import os
import secrets
from datetime import datetime
from db import (
    get_user_by_username,
    save_user,
    create_auth_token,
    delete_auth_token,
    get_user_by_id,
    list_session_data,
    update_user_password,
    revoke_all_user_tokens,
    get_user_by_email
)
from utils.auth import require_auth
from services.otp_service import OTPService

auth_bp = Blueprint('auth', __name__)


import ipaddress


def get_client_ip() -> str:
    """
    Safely extract client IP address.
    Never trust arbitrary X-Forwarded-For headers from untrusted clients.
    Wildcard '*' is strictly prohibited to prevent rate-limit bypass spoofing.
    Validates IP syntax using ipaddress before returning.
    """
    remote_addr = (request.remote_addr or "").strip()
    trusted_proxies_cfg = os.getenv("TRUSTED_PROXIES", "").strip()
    if not trusted_proxies_cfg or not remote_addr:
        return remote_addr

    # Disallow wildcard trust: '*' is inherently insecure on public-facing backends
    trusted_raw = [p.strip() for p in trusted_proxies_cfg.split(",") if p.strip() and p.strip() != "*"]
    if not trusted_raw:
        return remote_addr

    # Check if immediate sender (request.remote_addr) is an authorized proxy
    is_trusted = False
    try:
        remote_ip_obj = ipaddress.ip_address(remote_addr)
        for item in trusted_raw:
            try:
                if "/" in item:
                    if remote_ip_obj in ipaddress.ip_network(item, strict=False):
                        is_trusted = True
                        break
                else:
                    if remote_ip_obj == ipaddress.ip_address(item):
                        is_trusted = True
                        break
            except ValueError:
                continue
    except ValueError:
        return remote_addr

    if not is_trusted:
        return remote_addr

    # Immediate proxy is trusted; parse X-Forwarded-For safely
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if not forwarded:
        return remote_addr

    # In standard reverse proxies, client IP is the leftmost valid IP address
    for part in forwarded.split(","):
        candidate = part.strip()
        if candidate:
            try:
                ip_obj = ipaddress.ip_address(candidate)
                return str(ip_obj)
            except ValueError:
                continue

    return remote_addr

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"error": "invalid_request", "message": "Username and password required"}), 400
        
    existing = get_user_by_username(username)
    if existing:
        return jsonify({"error": "duplicate", "message": "Username already exists"}), 400
        
    password_hash = generate_password_hash(password)
    user_id = save_user(username, password_hash)
                 
    return jsonify({"message": "Registration successful"}), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    
    user = get_user_by_username(username)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "unauthorized", "message": "Invalid username or password"}), 401
        
    token = secrets.token_urlsafe(32)
    create_auth_token(user["id"], token)
                 
    res = make_response(jsonify({"token": token}), 200)
    is_secure = request.is_secure or os.getenv("FLASK_ENV") == "production"
    res.set_cookie('auth_token', token, httponly=True, samesite='Lax', secure=is_secure)
    return res

@auth_bp.route('/auth/otp/send', methods=['POST'])
def send_otp():
    data = request.get_json() or {}
    target = data.get('target', '')
    target_type = data.get('type', 'email')
    client_ip = get_client_ip()

    if not target:
        return jsonify({"error": "invalid_request", "message": f"{target_type.capitalize()} is required."}), 400

    success, message, meta = OTPService.send_otp(target, target_type, client_ip=client_ip)
    if not success:
        if "temporarily unavailable" in message.lower() or meta.get("error") == "service_unavailable":
            return jsonify({"error": "service_unavailable", "message": message, **meta}), 503
        status_code = 429 if "wait" in message.lower() or "too many requests" in message.lower() else 400
        return jsonify({"error": "otp_send_failed", "message": message, **meta}), status_code

    return jsonify({"success": True, "message": message, **meta}), 200

@auth_bp.route('/auth/otp/verify', methods=['POST'])
def verify_otp():
    data = request.get_json() or {}
    target = data.get('target', '')
    target_type = data.get('type', 'email')
    otp = data.get('otp', '')

    if not target or not otp:
        return jsonify({"error": "invalid_request", "message": "Target and OTP code are required."}), 400

    success, message = OTPService.verify_otp(target, target_type, otp)
    if not success:
        status_code = 503 if "temporarily unavailable" in message.lower() else 400
        return jsonify({"error": "verification_failed", "message": message}), status_code

    normalized_target, _ = OTPService.normalize_target(target, target_type)
    user = get_user_by_username(normalized_target)
    if not user:
        pwd_hash = generate_password_hash(f"otp_user_{secrets.token_hex(16)}")
        user_id = save_user(normalized_target, pwd_hash)
        user = get_user_by_id(user_id)

    token = secrets.token_urlsafe(32)
    create_auth_token(user["id"], token)

    res = make_response(jsonify({
        "success": True,
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "created_at": user.get("created_at")
        }
    }), 200)
    is_secure = request.is_secure or os.getenv("FLASK_ENV") == "production"
    res.set_cookie('auth_token', token, httponly=True, samesite='Lax', secure=is_secure)
    return res

@auth_bp.route('/logout', methods=['POST'])
def logout():
    cookie_token = request.cookies.get('auth_token')
    header_token = None
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        header_token = auth_header[7:].strip()

    if cookie_token:
        delete_auth_token(cookie_token)
    if header_token and header_token != cookie_token:
        delete_auth_token(header_token)
    
    response = make_response(jsonify({"message": "Logged out successfully"}))
    response.delete_cookie('auth_token')
    return response

@auth_bp.route('/me', methods=['GET'])
@require_auth
def me():
    # We get user_id from the request context set by @require_auth
    user_id = getattr(request, 'user_id', getattr(request, 'current_user_id', None))
    if not user_id:
         return jsonify({"error": "Not authenticated"}), 401
    
    user = get_user_by_id(user_id)
        
    if not user:
        return jsonify({"error": "User not found"}), 404
        
    sessions = list_session_data(user_id=user_id)
        
    return jsonify({
        "username": user["username"],
        "created_at": user["created_at"],
        "sessions": [{"session_id": s["session_id"], "filename": s.get("filename"), "created_at": s["created_at"]} for s in sessions]
    })

# --- Forgot Password with Mandatory OTP Verification ---

@auth_bp.route('/auth/password-reset/request', methods=['POST'])
def request_password_reset():
    data = request.get_json() or {}
    email = data.get('email', '')
    client_ip = get_client_ip()

    normalized_email, err = OTPService.normalize_target(email, 'email')
    if err:
        return jsonify({"error": "invalid_request", "message": "A valid email address is required."}), 400

    # Generic response returned to prevent account enumeration
    generic_msg = "If an account is associated with this email, a verification code has been sent."

    # 1. IP rate limiting (applies equally to existing and non-existing accounts)
    if client_ip:
        allowed_ip, ip_retry = OTPService.check_ip_rate_limit(client_ip, max_requests=20, window_seconds=3600)
        if not allowed_ip:
            return jsonify({
                "error": "rate_limited",
                "message": f"Too many requests from this IP. Please try again in {ip_retry} seconds.",
                "retry_after": ip_retry
            }), 429

    # 2. Target cooldown check (prevents email flooding without revealing account existence)
    can_send, _ = OTPService.can_resend(normalized_email, cooldown_seconds=60, purpose="password_reset")
    if not can_send:
        # Silently suppress duplicate dispatch during cooldown and return standard generic response
        return jsonify({"success": True, "message": generic_msg}), 200

    # 3. Lookup user
    user = get_user_by_email(normalized_email) or get_user_by_username(normalized_email)
    if user:
        success, msg, meta = OTPService.send_otp(normalized_email, "email", client_ip=client_ip, purpose="password_reset")
        if not success:
            if "temporarily unavailable" in msg.lower() or meta.get("error") == "service_unavailable":
                return jsonify({"error": "service_unavailable", "message": msg, **meta}), 503
            if "not configured" in msg.lower() or "failed" in msg.lower():
                return jsonify({"error": "delivery_failed", "message": msg}), 503
    else:
        # Non-existing account: record cooldown timestamp to ensure identical state timing, do not send email
        try:
            OTPService.record_cooldown(normalized_email, cooldown_seconds=60, purpose="password_reset")
        except Exception:
            pass

    return jsonify({"success": True, "message": generic_msg}), 200

@auth_bp.route('/auth/password-reset/verify', methods=['POST'])
def verify_password_reset_code():
    data = request.get_json() or {}
    email = data.get('email', '')
    otp = data.get('otp', '')

    if not email or not otp:
        return jsonify({"error": "invalid_request", "message": "Email and verification code are required."}), 400

    normalized_email, err = OTPService.normalize_target(email, 'email')
    if err:
        return jsonify({"error": "invalid_request", "message": "Invalid email address format."}), 400

    success, msg = OTPService.verify_otp(normalized_email, "email", otp, purpose="password_reset")
    if not success:
        status_code = 503 if "temporarily unavailable" in msg.lower() else 400
        return jsonify({"error": "verification_failed", "message": msg}), status_code

    user = get_user_by_email(normalized_email) or get_user_by_username(normalized_email)
    if not user:
        return jsonify({"error": "verification_failed", "message": "Invalid or expired verification code."}), 400

    # Issue short-lived, single-use reset authorization token
    reset_token = OTPService.create_password_reset_token(user["id"], normalized_email)
    return jsonify({
        "success": True,
        "message": "Code verified successfully.",
        "reset_token": reset_token
    }), 200

@auth_bp.route('/auth/password-reset/confirm', methods=['POST'])
def confirm_password_reset():
    data = request.get_json() or {}
    reset_token = data.get('reset_token', '')
    new_password = data.get('new_password', '')
    confirm_password = data.get('confirm_password', '')

    if not reset_token or not new_password or not confirm_password:
        return jsonify({"error": "invalid_request", "message": "Reset authorization token and passwords are required."}), 400

    if new_password != confirm_password:
        return jsonify({"error": "mismatch", "message": "Passwords do not match."}), 400

    if len(new_password) < 8:
        return jsonify({"error": "weak_password", "message": "Password must be at least 8 characters long."}), 400

    if not any(c.isalpha() for c in new_password) or not any(c.isdigit() or not c.isalnum() for c in new_password):
        return jsonify({"error": "weak_password", "message": "Password must contain both letters and numbers/special characters."}), 400

    # Atomically verify and consume reset authorization token (single use, prevents TOCTOU reuse)
    valid, msg, record = OTPService.verify_and_consume_password_reset_token(reset_token)
    if not valid or not record:
        status_code = 503 if "temporarily unavailable" in msg.lower() else 400
        return jsonify({"error": "invalid_token", "message": msg}), status_code

    user_id = record["user_id"]
    pwd_hash = generate_password_hash(new_password)
    update_user_password(user_id, pwd_hash)

    # Revoke all active sessions
    revoke_all_user_tokens(user_id)

    return jsonify({
        "success": True,
        "message": "Password reset successfully. Please log in with your new password."
    }), 200

# --- Forgot Username with Mandatory OTP Verification ---

@auth_bp.route('/auth/username-recovery/request', methods=['POST'])
def request_username_recovery():
    data = request.get_json() or {}
    email = data.get('email', '')
    client_ip = get_client_ip()

    normalized_email, err = OTPService.normalize_target(email, 'email')
    if err:
        return jsonify({"error": "invalid_request", "message": "A valid email address is required."}), 400

    generic_msg = "If an account is associated with this email, a verification code has been sent."

    # 1. IP rate limiting (applies equally to existing and non-existing accounts)
    if client_ip:
        allowed_ip, ip_retry = OTPService.check_ip_rate_limit(client_ip, max_requests=20, window_seconds=3600)
        if not allowed_ip:
            return jsonify({
                "error": "rate_limited",
                "message": f"Too many requests from this IP. Please try again in {ip_retry} seconds.",
                "retry_after": ip_retry
            }), 429

    # 2. Target cooldown check
    can_send, _ = OTPService.can_resend(normalized_email, cooldown_seconds=60, purpose="username_recovery")
    if not can_send:
        return jsonify({"success": True, "message": generic_msg}), 200

    # 3. Lookup user
    user = get_user_by_email(normalized_email) or get_user_by_username(normalized_email)
    if user:
        success, msg, meta = OTPService.send_otp(normalized_email, "email", client_ip=client_ip, purpose="username_recovery")
        if not success:
            if "temporarily unavailable" in msg.lower() or meta.get("error") == "service_unavailable":
                return jsonify({"error": "service_unavailable", "message": msg, **meta}), 503
            if "not configured" in msg.lower() or "failed" in msg.lower():
                return jsonify({"error": "delivery_failed", "message": msg}), 503
    else:
        try:
            OTPService.record_cooldown(normalized_email, cooldown_seconds=60, purpose="username_recovery")
        except Exception:
            pass

    return jsonify({"success": True, "message": generic_msg}), 200

@auth_bp.route('/auth/username-recovery/verify', methods=['POST'])
def verify_username_recovery():
    data = request.get_json() or {}
    email = data.get('email', '')
    otp = data.get('otp', '')

    if not email or not otp:
        return jsonify({"error": "invalid_request", "message": "Email and verification code are required."}), 400

    normalized_email, err = OTPService.normalize_target(email, 'email')
    if err:
        return jsonify({"error": "invalid_request", "message": "Invalid email address format."}), 400

    success, msg = OTPService.verify_otp(normalized_email, "email", otp, purpose="username_recovery")
    if not success:
        status_code = 503 if "temporarily unavailable" in msg.lower() else 400
        return jsonify({"error": "verification_failed", "message": msg}), status_code

    user = get_user_by_email(normalized_email) or get_user_by_username(normalized_email)
    if not user:
        return jsonify({"error": "verification_failed", "message": "Invalid or expired verification code."}), 400

    # Disclose username ONLY after successful server-side OTP verification
    return jsonify({
        "success": True,
        "username": user["username"],
        "message": "Username recovered successfully."
    }), 200
