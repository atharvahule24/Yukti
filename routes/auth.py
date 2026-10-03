from flask import Blueprint, request, jsonify, make_response
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from datetime import datetime
from db import get_user_by_username, save_user, create_auth_token, delete_auth_token, get_user_by_id, list_session_data
from utils.auth import require_auth

auth_bp = Blueprint('auth', __name__)

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
                 
    return jsonify({"token": token}), 200

@auth_bp.route('/logout', methods=['POST'])
def logout():
    token = request.cookies.get('auth_token')
    if token:
        delete_auth_token(token)
    
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
