from utils.auth import require_session_owner
from flask import Blueprint, jsonify
from routes.store import session_store
from utils.json_safe import json_error
from utils.validation import validate_session_id

notes_bp = Blueprint('notes', __name__)

@notes_bp.route('/notes/<session_id>', methods=['GET'])
@require_session_owner
def get_notes(session_id):
    valid, error = validate_session_id(session_id)
    if not valid:
        return json_error(error)
    if session_id not in session_store:
        return jsonify({"error": "not_found"}), 404
        
    notes = session_store[session_id].get("notes")
    if not notes:
        return jsonify({"points": []})
    return jsonify(notes)

@notes_bp.route('/notes/generate/<session_id>', methods=['POST'])
@require_session_owner
def generate_notes(session_id):
    valid, error = validate_session_id(session_id)
    if not valid:
        return json_error(error)
    if session_id not in session_store:
        return jsonify({"error": "not_found"}), 404

    from tasks import generate_notes_task
    task = generate_notes_task.delay(session_id)
    return jsonify({"task_id": task.id, "status": "processing"}), 202
