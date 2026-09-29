from utils.auth import require_session_owner, require_auth, get_current_user_id
from flask import Blueprint, jsonify
from routes.store import session_store
from db import get_progress as get_session_progress
from db import list_session_data

sessions_bp = Blueprint('sessions', __name__)

@sessions_bp.route('/sessions', methods=['GET'])
@require_auth
def get_sessions():
    sessions_list = []
    # Fetch only sessions belonging to current user
    user_sessions = list_session_data(get_current_user_id())
    for sdata in user_sessions:
        sessions_list.append({
            "id": sdata["id"],
            "title": sdata["title"],
            "original_filename": sdata.get("original_filename", sdata["title"]),
            "created_at": sdata["created_at"],
            "chunk_count": sdata.get("chunk_count", 0)
        })
    # Sort by created_at descending
    sessions_list.sort(key=lambda x: x["created_at"], reverse=True)
    return jsonify({"sessions": sessions_list})

@sessions_bp.route('/sessions/<session_id>', methods=['DELETE'])
@require_session_owner
def delete_session(session_id):
    if session_id in session_store:
        del session_store[session_id]
        return jsonify({"deleted": True})
    return jsonify({"error": "not_found"}), 404

@sessions_bp.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "version": "1.0.0"})

@sessions_bp.route('/progress/<session_id>', methods=['GET'])
@require_session_owner
def progress(session_id):
    if session_id not in session_store:
        return jsonify({"error": "not_found"}), 404
    return jsonify(get_session_progress(session_id))
