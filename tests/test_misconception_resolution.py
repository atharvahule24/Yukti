import pytest
import db

def test_misconception_resolution(app_client):
    session_id = "test_session_misc"
    concept = "Gravity"
    
    # 1. Two different misconceptions can exist under the same concept
    misc_a = "Heavy objects fall faster"
    misc_b = "Gravity only acts on Earth"
    
    db.record_misconception(session_id, concept, "high", misc_a)
    db.record_misconception(session_id, concept, "high", misc_b)
    
    active = db.get_active_misconceptions(session_id, concept)
    assert len(active) == 2
    active_texts = [m["misconception"] for m in active]
    assert misc_a in active_texts
    assert misc_b in active_texts
    
    # 2. Resolving misconception A does NOT resolve misconception B
    db.resolve_misconceptions(session_id, concept, misconception_text=misc_a)
    
    active = db.get_active_misconceptions(session_id, concept)
    assert len(active) == 1
    assert active[0]["misconception"] == misc_b
    
    # 3. Missing misconception payload does not resolve all misconceptions
    # We will test this via the grade_intervention_answer API
    db.record_misconception(session_id, concept, "high", misc_a) # Re-add A
    
    # Now simulate intervention grading where misconception payload is MISSING
    response = app_client.post('/api/quiz/intervention-grade', json={
        "session_id": session_id,
        "concept": concept,
        "question": "What happens?",
        "user_answer": "Nothing",
        # misconception payload omitted
    })
    
    # Check that both are still active because the missing payload should prevent any resolution
    active = db.get_active_misconceptions(session_id, concept)
    assert len(active) == 2
    
    # 4. Intervention reassessment resolves only the targeted misconception
    # To mock the intervention grade passing, we need to mock the AI.
    with pytest.MonkeyPatch.context() as m:
        # Mock the generator invoke
        from langchain_core.runnables import Runnable
        class MockChain:
            def invoke(self, *args, **kwargs):
                return '{"score": 10, "correct": true, "misconception": null}'
        
        class MockGenerator:
            def __init__(self, *args, **kwargs):
                self.chain = MockChain()
                
        m.setattr("routes.quiz.Generator", MockGenerator)
        
        response = app_client.post('/api/quiz/intervention-grade', json={
            "session_id": session_id,
            "concept": concept,
            "question": "What happens?",
            "user_answer": "It acts everywhere",
            "misconception": misc_b
        })
        
        assert response.status_code == 200
        # Check that B is resolved, but A remains
        active = db.get_active_misconceptions(session_id, concept)
        assert len(active) == 1
        assert active[0]["misconception"] == misc_a

    # 5. Normal quiz grading does not resolve misconceptions
    with pytest.MonkeyPatch.context() as m:
        # We need to test the /quiz/grade route without is_reassessment=True
        class MockChain:
            def invoke(self, *args, **kwargs):
                return '{"score": 10, "feedback": "Great", "correct_concepts": [], "missed_concepts": []}'
        
        class MockGenerator:
            def __init__(self, *args, **kwargs):
                self.chain = MockChain()
                
        m.setattr("routes.quiz.Generator", MockGenerator)
        
        # We must add A again to be safe
        response = app_client.post('/api/quiz/grade', json={
            "session_id": session_id,
            "concept": concept,
            "question": "Normal quiz question?",
            "user_answer": "Normal answer",
            "sample_answer": "Normal sample",
            "is_reassessment": False
        })
        
        assert response.status_code == 200
        # A should still be active because normal quiz grading shouldn't touch it
        active = db.get_active_misconceptions(session_id, concept)
        assert len(active) == 1
        assert active[0]["misconception"] == misc_a

    # 6. Targeted reassessment resolves only the targeted misconception
    with pytest.MonkeyPatch.context() as m:
        class MockChain:
            def invoke(self, *args, **kwargs):
                return '{"score": 10, "feedback": "Great", "correct_concepts": [], "missed_concepts": []}'
        
        class MockGenerator:
            def __init__(self, *args, **kwargs):
                self.chain = MockChain()
                
        m.setattr("routes.quiz.Generator", MockGenerator)
        
        response = app_client.post('/api/quiz/grade', json={
            "session_id": session_id,
            "concept": concept,
            "question": "Reassessment question?",
            "user_answer": "Good answer",
            "sample_answer": "Sample",
            "is_reassessment": True,
            "misconception": misc_a
        })
        
        assert response.status_code == 200
        # A should now be resolved
        active = db.get_active_misconceptions(session_id, concept)
        assert len(active) == 0

