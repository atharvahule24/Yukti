from flask import Blueprint, jsonify

from db import get_learning_analytics
from agents.adaptive_orchestrator import get_next_learning_action


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