from utils.auth import require_session_owner, require_auth, get_current_user_id
from flask import Blueprint, jsonify, request
from db import get_learning_analytics, get_cumulative_learning_analytics
from agents.adaptive_orchestrator import get_next_learning_action
from agents.video_recommender import recommend_video_search

learner_bp = Blueprint("learner", __name__)


@learner_bp.route("/learner/analytics/me", methods=["GET"])
@require_auth
def cumulative_learner_analytics():
    try:
        user_id = get_current_user_id()
        return jsonify(get_cumulative_learning_analytics(user_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@learner_bp.route("/learner/analytics/<session_id>", methods=["GET"])
@require_session_owner
def learner_analytics(session_id):
    try:
        return jsonify(get_learning_analytics(session_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@learner_bp.route("/learner/next-action/<session_id>", methods=["GET"])
@require_session_owner
def learner_next_action(session_id):
    try:
        return jsonify(get_next_learning_action(session_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@learner_bp.route("/learner/video-recommendation/<session_id>", methods=["GET", "POST"])
@require_session_owner
def learner_video_recommendation(session_id):
    try:
        data = request.get_json(silent=True) or {}
        concept = request.args.get("concept") or data.get("concept")
        question = request.args.get("question") or data.get("question")
        feedback = request.args.get("feedback") or data.get("feedback")
        study_tip = request.args.get("study_tip") or data.get("study_tip")

        # Fallback to the latest check-in concept for this session if not provided
        if not concept:
            try:
                from db import supabase
                res = supabase.table("metacognitive_checkins").select("concept").eq("session_id", session_id).order("id", desc=True).limit(1).execute()
                if res.data and res.data[0].get("concept"):
                    concept = res.data[0]["concept"]
            except Exception:
                pass

        plan = get_next_learning_action(session_id, concept=concept)

        target_concept = concept or plan.get("concept", "")
        recommendation = recommend_video_search(
            concept=target_concept,
            difficulty=plan.get("difficulty", "medium"),
            action=plan.get("learning_path", {}).get("action", "review"),
            misconception=plan.get("learning_path", {}).get("misconception"),
            question=question,
            feedback=feedback,
            study_tip=study_tip,
        )

        return jsonify({
            "learning_path": plan,
            "video": recommendation,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500