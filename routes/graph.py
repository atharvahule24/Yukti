from utils.auth import require_session_owner
from flask import Blueprint, jsonify, request
from routes.store import session_store
from utils.json_safe import json_error, parse_json_request
from utils.validation import validate_session_id

graph_bp = Blueprint('graph', __name__)

@graph_bp.route('/graph/<session_id>', methods=['GET'])
@require_session_owner
def get_graph(session_id):
    valid, error = validate_session_id(session_id)
    if not valid:
        return json_error(error)
    if session_id not in session_store:
        return jsonify({"error": "not_found"}), 404
        
    graph_data = session_store[session_id].get("graph")
    if not graph_data or not isinstance(graph_data, dict):
        return jsonify({"nodes": [], "links": []})

    nodes = graph_data.get("nodes", [])
    links = graph_data.get("links") or graph_data.get("edges") or []
    if len(nodes) <= 1 and len(links) == 0:
        return jsonify({"nodes": [], "links": []})

    if "edges" in graph_data and "links" not in graph_data:
        graph_data["links"] = graph_data["edges"]
    elif "links" in graph_data and "edges" not in graph_data:
        graph_data["edges"] = graph_data["links"]
        
    return jsonify(graph_data)

@graph_bp.route('/graph/generate/<session_id>', methods=['POST'])
@require_session_owner
def generate_graph(session_id):
    valid, error = validate_session_id(session_id)
    if not valid:
        return json_error(error)
    if session_id not in session_store:
        return jsonify({"error": "not_found"}), 404

    force = False
    if request.is_json:
        data, parse_err = parse_json_request(request)
        if not parse_err and isinstance(data, dict):
            force = bool(data.get("force", False))

    from tasks import generate_graph_task
    task = generate_graph_task.delay(session_id, force=force)
    return jsonify({"task_id": task.id, "status": "processing"}), 202
