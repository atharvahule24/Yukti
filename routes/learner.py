from flask import Blueprint, jsonify, request
from db import get_learning_analytics
from agents.adaptive_orchestrator import get_next_learning_action
from agents.video_recommender import recommend_video_search

learner_bp = Blueprint("learner", __name__)


@learner_bp.route("/learner/analytics/<session_id>", methods=["GET"])
def learner_analytics(session_id):
    try:
        return jsonify(get_learning_analytics(session_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@learner_bp.route("/learner/next-action/<session_id>", methods=["GET"])
def learner_next_action(session_id):
    try:
        return jsonify(get_next_learning_action(session_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@learner_bp.route("/learner/video-recommendation/<session_id>", methods=["GET"])
def learner_video_recommendation(session_id):
    try:
        plan = get_next_learning_action(session_id)

        recommendation = recommend_video_search(
            concept=plan.get("concept", ""),
            difficulty=plan.get("difficulty", "medium"),
            action=plan.get("learning_path", {}).get("action", "review"),
            misconception=plan.get("learning_path", {}).get("misconception"),
        )

        return jsonify({
            "learning_path": plan,
            "video": recommendation,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500