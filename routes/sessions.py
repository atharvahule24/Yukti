import os
from utils.auth import require_session_owner, require_auth, get_current_user_id
from flask import Blueprint, jsonify
from routes.store import session_store
from db import get_progress as get_session_progress
from db import list_session_data

from datetime import datetime, timezone

sessions_bp = Blueprint('sessions', __name__)

def determine_session_status(sdata: dict) -> str:
    raw_status = str(sdata.get("status") or "").lower().strip()
    if raw_status in ("failed", "failure", "error"):
        return "failed"
    if raw_status in ("ready", "completed", "success"):
        return "ready"

    # If task_id is present, check live Celery task status first
    task_id = sdata.get("task_id")
    if task_id:
        try:
            from celery_app import celery
            task = celery.AsyncResult(task_id)
            if task.state == "FAILURE":
                return "failed"
            elif task.state == "SUCCESS":
                return "ready"
            elif task.state in ("PENDING", "STARTED", "PROGRESS"):
                # Actively running or queued task - never mark failed solely due to age
                return "processing"
        except Exception:
            pass

    if raw_status in ("processing", "pending"):
        created_at_str = sdata.get("created_at")
        if created_at_str:
            try:
                clean_str = created_at_str.replace("Z", "+00:00")
                created_dt = datetime.fromisoformat(clean_str)
                now = datetime.now(timezone.utc) if created_dt.tzinfo else datetime.utcnow()
                # Stale unconfirmed processing session exceeding 1 hour
                if (now - created_dt).total_seconds() > 3600:
                    return "failed"
            except Exception:
                pass
        return "processing"

    # Legacy records without explicit status
    if sdata.get("chunk_count", 0) > 0 or bool(sdata.get("full_text") or sdata.get("text")):
        return "ready"

    # Stale empty sessions without text or chunks
    created_at_str = sdata.get("created_at")
    if created_at_str:
        try:
            clean_str = created_at_str.replace("Z", "+00:00")
            created_dt = datetime.fromisoformat(clean_str)
            now = datetime.now(timezone.utc) if created_dt.tzinfo else datetime.utcnow()
            if (now - created_dt).total_seconds() <= 3600:
                return "processing"
        except Exception:
            pass

    return "failed"

@sessions_bp.route('/sessions', methods=['GET'])
@require_auth
def get_sessions():
    sessions_list = []
    seen_ids = set()
    user_sessions = list_session_data(get_current_user_id())
    for sdata in user_sessions:
        sid = sdata.get("id") or sdata.get("session_id")
        if not sid or sid in seen_ids:
            continue

        status = determine_session_status(sdata)
        if status in ("failed", "failure"):
            continue

        seen_ids.add(sid)
        sessions_list.append({
            "id": sid,
            "title": sdata.get("title") or sdata.get("filename") or "Untitled",
            "original_filename": sdata.get("original_filename", sdata.get("title", "Untitled")),
            "created_at": sdata.get("created_at"),
            "chunk_count": sdata.get("chunk_count", 0),
            "status": status,
        })
    # Sort by created_at descending
    sessions_list.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
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
    return jsonify({
        "status": "ok",
        "version": "1.0.0",
        "resend_configured": bool(os.getenv("RESEND_API_KEY"))
    })

@sessions_bp.route('/progress/<session_id>', methods=['GET'])
@require_session_owner
def progress(session_id):
    if session_id not in session_store:
        return jsonify({"error": "not_found"}), 404
    return jsonify(get_session_progress(session_id))
