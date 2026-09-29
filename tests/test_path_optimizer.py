import pytest
from unittest.mock import patch, MagicMock
from agents.path_optimizer import optimize_learning_path
from agents.adaptive_question_engine import get_adaptive_question_plan
import db

def test_path_optimizer(app_client):
    session_id = "test_session_opt"
    concept = "Newton's First Law"
    
    print("Testing no learner state")
    # Test: no learner state
    path = optimize_learning_path(session_id, concept)
    # Default is learn or practice
    assert path["action"] in ("learn", "practice", "review")
    
    print("Testing active misconception")
    # Test: active misconception -> targeted_misconception_review
    db.update_learner_state(session_id, [], [concept], 2.0, "high") # Add learner state with low recent_score
    db.record_misconception(session_id, concept, "high", "Force implies velocity")
    path = optimize_learning_path(session_id, concept)
    assert path["action"] == "targeted_misconception_review"
    assert path["misconception"] == "Force implies velocity"
    
    print("Testing low mastery")
    # Test: low mastery -> review/practice
    # Clear misconception
    db.resolve_misconceptions(session_id, concept, "Force implies velocity")
    db.update_learner_state(session_id, [], [concept], 4.0, None)
    path = optimize_learning_path(session_id, concept)
    assert path["action"] in ("step_by_step_review", "example_based_review", "review", "practice", "prerequisite_review")
    
    # Test: high performance + low confidence -> confidence_reinforcement
    # For high performance, we need to pass correct concepts and a high score.
    db.update_learner_state(session_id, [concept], [], 9.0, None)
    db.record_metacognitive_checkin(session_id, concept, 1) # Low confidence
    path = optimize_learning_path(session_id, concept)
    assert path["action"] == "confidence_reinforcement"

    # Test: sufficient mastery -> advance
    for _ in range(10):
        db.update_learner_state(session_id, [concept], [], 10.0, None)
    db.record_metacognitive_checkin(session_id, concept, 3) # High confidence
    path = optimize_learning_path(session_id, concept)
    assert path["action"] == "advance"


def test_adaptive_question_engine(app_client):
    session_id = "test_engine"
    concept = "Photosynthesis"
    learning_path = {
        "concept": concept,
        "action": "targeted_misconception_review",
        "difficulty": "medium",
        "misconception": "Plants get food from soil"
    }
    
    db.record_misconception(session_id, concept, "high", "Plants get food from soil")

    plan = get_adaptive_question_plan(session_id=session_id, concept=concept, learning_path=learning_path)
    
    assert plan["concept"] == concept
    assert plan["difficulty"] == "easy"
    assert plan["question_type"] in ("diagnostic", "conceptual")
    assert plan["misconception"] == "Plants get food from soil"
