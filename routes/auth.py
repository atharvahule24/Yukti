from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from datetime import datetime
from db import get_conn

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"error": "invalid_request", "message": "Username and password required"}), 400
        
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if existing:
            return jsonify({"error": "duplicate", "message": "Username already exists"}), 400
            
        password_hash = generate_password_hash(password)
        now = datetime.utcnow().isoformat()
        
        conn.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)", 
                     (username, password_hash, now))
                     
    return jsonify({"message": "Registration successful"}), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    
    with get_conn() as conn:
        user = conn.execute("SELECT id, password_hash FROM users WHERE username=?", (username,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            return jsonify({"error": "unauthorized", "message": "Invalid username or password"}), 401
            
        token = secrets.token_urlsafe(32)
        now = datetime.utcnow().isoformat()
        
        conn.execute("INSERT INTO auth_tokens (token, user_id, created_at) VALUES (?, ?, ?)", 
                     (token, user["id"], now))
                     
    return jsonify({"token": token}), 200
