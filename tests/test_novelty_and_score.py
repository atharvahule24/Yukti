import pytest
from routes.quiz import is_similar_question, normalize_question

def test_question_novelty_logic():
    seen = ["What is the capital of France?", "Explain Newton's First Law."]
    
    # 1. Exact duplicate -> rejected
    assert is_similar_question("What is the capital of France?", seen) == True
    
    # 2. Semantically similar question -> rejected
    # "What's the capital of France?" normalizes similarly
    assert is_similar_question("Whats the capital of France?", seen) == True
    
    # 3. Genuinely different question -> accepted
    assert is_similar_question("What is the capital of Germany?", seen) == False
    
def test_insufficient_novel_questions(app_client):
    import json
    session_id = "test_novelty"
    app_client.post(f'/api/process-url', json={"url": "http://example.com", "session_id": session_id})
    # Since we can't easily mock the internal generate_and_filter directly, we mock the Generator to always return the same question
    
    with pytest.MonkeyPatch.context() as m:
        class MockChain:
            def invoke(self, *args, **kwargs):
                return json.dumps({
                    "mcq": [{"question": "Same question every time", "options": ["A", "B", "C", "D"], "answer": "A"}],
                    "short_answer": [{"question": "Same short question", "sample_answer": "A"}]
                })
        
        class MockGenerator:
            def __init__(self, *args, **kwargs):
                self.chain = MockChain()
                
        m.setattr("routes.quiz.Generator", MockGenerator)
        
        # We need to set some full_text in session_store to pass validation
        from routes.quiz import session_store
        session_store[session_id] = {"full_text": "Sample text " * 100}
        
        # When we request 3 questions, it will return the exact same 1 question 3 times, 
        # so length will be 1, which is < 3. It should raise RuntimeError and return 400.
        response = app_client.post(f'/api/quiz/generate/{session_id}', json={"count": 3, "concept": "Test"})
        
        assert response.status_code == 400
        data = response.get_json()
        assert "Insufficient novel questions generated" in data["error"]

def test_score_parsing(app_client):
    session_id = "test_score_parsing"
    
    from routes.quiz import session_store
    session_store[session_id] = {"full_text": "text"}
    
    def simulate_grading(score_value):
        with pytest.MonkeyPatch.context() as m:
            import json
            class MockChain:
                def invoke(self, *args, **kwargs):
                    return json.dumps({"score": score_value, "feedback": "FB", "correct_concepts": [], "missed_concepts": []})
            
            class MockGenerator:
                def __init__(self, *args, **kwargs):
                    self.chain = MockChain()
                    
            m.setattr("routes.quiz.Generator", MockGenerator)
            
            # Need to mock update_mastery_from_assessment so it doesn't fail on DB
            m.setattr("routes.quiz.update_mastery_from_assessment", lambda *a, **kw: {})
            m.setattr("routes.quiz.detect_misconception", lambda *a, **kw: None)
            
            response = app_client.post('/api/quiz/grade', json={
                "session_id": session_id,
                "concept": "Test",
                "question": "Q",
                "user_answer": "A",
                "sample_answer": "S"
            })
            return response.get_json()

    # Numeric integer
    assert simulate_grading(8).get("score") == 8.0
    # Numeric float
    assert simulate_grading(8.5).get("score") == 8.5
    # Numeric string
    assert simulate_grading("8").get("score") == 8.0
    assert simulate_grading("8.5").get("score") == 8.5
    # "7/10"
    assert simulate_grading("7/10").get("score") == 7.0
    # Invalid/non-numeric string - falls back to 0.0 usually or handles it
    assert simulate_grading("invalid").get("score") == 0.0
    # Missing score
    assert simulate_grading(None).get("score") == 0.0

