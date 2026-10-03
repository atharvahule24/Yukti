import functools
from flask import request, jsonify
from db import get_user_id_by_token, supabase

def require_auth(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        else:
            token = request.args.get("token")
            
        if not token:
            return jsonify({"error": "unauthorized", "message": "Missing or invalid token"}), 401
        
        user_id = get_user_id_by_token(token)
        if not user_id:
            return jsonify({"error": "unauthorized", "message": "Invalid token"}), 401
        
        request.current_user_id = user_id
        
        return f(*args, **kwargs)
    return decorated_function

def verify_session_owner(session_id, user_id):
    res = supabase.table("sessions").select("user_id").eq("session_id", session_id).maybe_single().execute()
    row = res.data
    if not row:
        return False, 404
    if row["user_id"] != user_id:
        return False, 403
    return True, 200

def get_current_user_id():
    return getattr(request, 'current_user_id', None)

def require_session_owner(f):
    @functools.wraps(f)
    @require_auth
    def decorated_function(*args, **kwargs):
        session_id = kwargs.get('session_id')
        if not session_id:
            if request.is_json:
                data = request.get_json(silent=True) or {}
                session_id = data.get('session_id')
            else:
                session_id = request.form.get('session_id')
        if not session_id:
            session_id = request.args.get('session_id')
                
        if session_id:
            valid, status_code = verify_session_owner(session_id, request.current_user_id)
            if not valid:
                if status_code == 404:
                    return jsonify({"error": "not_found", "message": "Session not found"}), 404
                return jsonify({"error": "forbidden", "message": "Access denied"}), 403
        else:
            return jsonify({"error": "bad_request", "message": "Missing session_id"}), 400
            
        return f(*args, **kwargs)
    return decorated_function
