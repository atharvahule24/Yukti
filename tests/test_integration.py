import pytest
import db
from agents.path_optimizer import optimize_learning_path

def test_critical_adaptive_flow(app_client):
    session_id = "test_integration"
    concept = "Kinematics"
    
    from routes.quiz import session_store
    session_store[session_id] = {"full_text": "Physics text " * 100}
    
    # 1. Normal assessment -> wrong answer -> misconception detected
    with pytest.MonkeyPatch.context() as m:
        import json
        class MockChain:
            def invoke(self, *args, **kwargs):
                return json.dumps({
                    "score": 3.0, 
                    "feedback": "Incorrect.", 
                    "correct_concepts": [], 
                    "missed_concepts": [concept],
                    "misconceptions": [
                        {"misconception": "Acceleration is velocity", "severity": "high", "evidence": "Used v instead of a", "suggested_intervention": "Explain diff"}
                    ]
                })
        
        class MockGenerator:
            def __init__(self, *args, **kwargs):
                self.chain = MockChain()
                
        m.setattr("routes.quiz.Generator", MockGenerator)
        
        # We need to ensure we mock get_active_misconceptions inside AI chain if needed, but it should be recorded by detect_misconception
        # We will mock detect_misconception to ensure it writes to DB as expected in the flow, OR just let it run if it's hitting our mock.
        # Actually detect_misconception runs its own LLM call. Let's mock the LLM for detect_misconception.
        m.setattr("agents.misconception_detector.Generator", MockGenerator)
        
        response = app_client.post('/quiz/grade', json={
            "session_id": session_id,
            "concept": concept,
            "question": "What is acceleration?",
            "user_answer": "It is how fast you go",
            "sample_answer": "Rate of change of velocity",
            "is_reassessment": False
        })
        
        assert response.status_code == 200
        grading = response.get_json()
        assert grading["score"] == 3.0
        
    # Verify misconception was detected and recorded
    active = db.get_active_misconceptions(session_id, concept)
    assert len(active) == 1
    assert active[0]["misconception"] == "Acceleration is velocity"
    
    # 2. Learner state updated
    state = db.get_learner_state(session_id)
    assert len(state) == 1
    
    # 3. Path optimizer selects targeted_misconception_review
    path = optimize_learning_path(session_id, concept)
    assert path["action"] == "targeted_misconception_review"
    assert path["misconception"] == "Acceleration is velocity"
    
    # 4. Targeted intervention/reassessment generated
    with pytest.MonkeyPatch.context() as m:
        import json
        class MockChainReassess:
            def invoke(self, *args, **kwargs):
                return json.dumps({
                    "short_answer": [{
                        "question": "Intervention question",
                        "sample_answer": "Correct answer"
                    }]
                })
        class MockGeneratorReassess:
            def __init__(self, *args, **kwargs):
                self.chain = MockChainReassess()
        m.setattr("routes.quiz.Generator", MockGeneratorReassess)
        
        res_reassess = app_client.post(f'/quiz/reassess/{session_id}', json={"concept": concept})
        assert res_reassess.status_code == 200
        reassessment_q = res_reassess.get_json()
        assert "question" in reassessment_q
        
    # (Let's add another unrelated misconception to verify it is NOT resolved)
    db.record_misconception(session_id, concept, "medium", "Another unrelated issue")
    
    # 5. Successful reassessment -> only targeted misconception resolved
    with pytest.MonkeyPatch.context() as m:
        import json
        class MockChainSuccess:
            def invoke(self, *args, **kwargs):
                return json.dumps({"score": 9.0, "feedback": "Good", "correct": True})
        class MockGeneratorSuccess:
            def __init__(self, *args, **kwargs):
                self.chain = MockChainSuccess()
        m.setattr("routes.quiz.Generator", MockGeneratorSuccess)
        
        # We pass the targeted misconception we are resolving
        res_grade = app_client.post('/quiz/intervention-grade', json={
            "session_id": session_id,
            "concept": concept,
            "question": "Intervention question",
            "user_answer": "Correct answer",
            "misconception": "Acceleration is velocity"
        })
        assert res_grade.status_code == 200
        
    # Verify ONLY targeted misconception is resolved
    active_after = db.get_active_misconceptions(session_id, concept)
    assert len(active_after) == 1
    assert active_after[0]["misconception"] == "Another unrelated issue"
    
    # 6. Next learning action recalculated
    path_after = optimize_learning_path(session_id, concept)
    # Action should no longer be targeted_misconception_review for "Acceleration is velocity"
    # It might target the new misconception, or move on to review.
    assert path_after["misconception"] != "Acceleration is velocity"
