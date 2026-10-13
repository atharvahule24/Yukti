import os
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import dotenv

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

dotenv.load_dotenv(WORKSPACE_ROOT / ".env")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_key")

from flask import Flask
from routes.quiz import quiz_bp, is_similar_question, normalize_question
from agents.prompts import QUIZ_MCQ_PROMPT

class TestNoveltyScoreAndQuizContract(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(quiz_bp, url_prefix='/api')
        self.client = self.app.test_client()

        self.session_id = "test-quiz-session-001"
        self.full_text = (
            "Photosynthesis is the biological process by which green plants synthesize nutrients. "
            "Photosynthesis occurs inside chloroplasts. "
            "Chlorophyll absorbs blue and red light and reflects green light. "
            "During the light-dependent reactions, ATP and NADPH are synthesized to power the Calvin cycle. "
            "Carbon dioxide is fixed into carbohydrates by the enzyme Rubisco."
        )
        self.memory_store = {
            self.session_id: {
                "full_text": self.full_text,
                "quiz_history": [],
                "quiz": None,
            }
        }
        self.adaptive_context = {
            "question_plan": {
                "concept": "Photosynthesis",
                "difficulty": "medium",
                "target": "practice",
                "question_type": "conceptual",
                "reason": "Reinforce core photosynthetic concepts"
            },
            "action": "quiz",
            "concept": "Photosynthesis"
        }

    def test_question_novelty_logic(self):
        """Preserved test: Exact and semantically similar questions rejected, different accepted."""
        seen = ["What is the capital of France?", "Explain Newton's First Law."]
        self.assertTrue(is_similar_question("What is the capital of France?", seen))
        self.assertTrue(is_similar_question("Whats the capital of France?", seen))
        self.assertFalse(is_similar_question("What is the capital of Germany?", seen))

    @patch('utils.auth.get_user_id_by_token', return_value=1)
    @patch('utils.auth.verify_session_owner', return_value=(True, 200))
    def test_score_parsing(self, mock_owner, mock_auth):
        """Preserved test: Grade endpoint parses various numeric/string score formats."""
        def simulate_grading(score_value):
            class MockChain:
                def invoke(self, *args, **kwargs):
                    return json.dumps({
                        "score": score_value,
                        "feedback": "FB",
                        "correct_concepts": [],
                        "missed_concepts": []
                    })

            class MockGen:
                def __init__(self, *args, **kwargs):
                    self.chain = MockChain()

            with patch('routes.quiz.Generator', MockGen), \
                 patch('routes.quiz.update_mastery_from_assessment', return_value={}), \
                 patch('routes.quiz.detect_misconception', return_value=None), \
                 patch('routes.quiz.record_quiz_score', return_value=None), \
                 patch('routes.quiz.record_misconception', return_value=None), \
                 patch('routes.quiz.session_store', self.memory_store):
                resp = self.client.post(
                    '/api/quiz/grade',
                    headers={'Authorization': 'Bearer test-token'},
                    json={
                        "session_id": self.session_id,
                        "concept": "Photosynthesis",
                        "question": "Where does photosynthesis occur?",
                        "user_answer": "In chloroplasts",
                        "sample_answer": "Photosynthesis occurs inside chloroplasts."
                    }
                )
                return resp.get_json() or {}

        self.assertEqual(simulate_grading(8).get("score"), 8.0)
        self.assertEqual(simulate_grading(8.5).get("score"), 8.5)
        self.assertEqual(simulate_grading("8").get("score"), 8.0)
        self.assertEqual(simulate_grading("8.5").get("score"), 8.5)
        self.assertEqual(simulate_grading("7/10").get("score"), 7.0)
        self.assertEqual(simulate_grading("invalid").get("score"), 0.0)
        self.assertEqual(simulate_grading(None).get("score"), 0.0)

    @patch('utils.auth.get_user_id_by_token', return_value=1)
    @patch('utils.auth.verify_session_owner', return_value=(True, 200))
    def test_insufficient_novel_questions(self, mock_owner, mock_auth):
        """Preserved test: Returns 400 when generator cannot produce enough novel questions."""
        class MockChain:
            def invoke(self, *args, **kwargs):
                return json.dumps({
                    "mcq": [{"question": "Same question every time", "options": ["A", "B", "C", "D"], "answer": "A"}],
                    "short_answer": [{"question": "Same short question", "sample_answer": "A"}]
                })

        class MockGen:
            def __init__(self, *args, **kwargs):
                self.chain = MockChain()

        with patch('routes.quiz.Generator', MockGen), \
             patch('routes.quiz.get_next_learning_action', return_value=self.adaptive_context), \
             patch('routes.quiz.session_store', self.memory_store):
            resp = self.client.post(
                f'/api/quiz/generate/{self.session_id}',
                headers={'Authorization': 'Bearer test-token'},
                json={"count": 3, "concept": "Photosynthesis"}
            )

        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("Insufficient novel questions generated", data["error"])

    def test_prompt_no_hardcoded_five(self):
        """QUIZ_MCQ_PROMPT communicates batch size dynamically without hardcoding 5."""
        self.assertNotIn("Generate exactly 5 multiple choice questions.", QUIZ_MCQ_PROMPT)
        self.assertIn("Generate the requested number of multiple choice questions.", QUIZ_MCQ_PROMPT)

    @patch('utils.auth.get_user_id_by_token', return_value=1)
    @patch('utils.auth.verify_session_owner', return_value=(True, 200))
    def test_validator_response_without_option_evidence(self, mock_owner, mock_auth):
        """Validator omitting option_evidence accepts grounded MCQs."""
        def mock_invoke(inputs):
            q_prompt = inputs.get("question", "")
            if "mcq" in q_prompt and "STUDY MATERIAL:" not in q_prompt:
                return json.dumps({
                    "mcq": [{
                        "question": "Where does photosynthesis occur inside green plants?",
                        "options": ["Inside chloroplasts", "In mitochondria", "In the cell wall", "In ribosomes"],
                        "answer": 0,
                        "difficulty": "medium",
                        "concept": "Photosynthesis",
                        "explanation": "Photosynthesis occurs inside chloroplasts as stated in the text."
                    }]
                })
            elif "STUDY MATERIAL:" in q_prompt:
                return json.dumps({
                    "valid": True,
                    "reason": "Directly stated in the context.",
                    "question_evidence": "Photosynthesis occurs inside chloroplasts.",
                    "answer_evidence": "Photosynthesis occurs inside chloroplasts."
                })
            elif "short_answer" in q_prompt:
                return json.dumps({
                    "short_answer": [{
                        "question": "Which enzyme fixes carbon dioxide into carbohydrates?",
                        "sample_answer": "Rubisco",
                        "concept": "Photosynthesis",
                        "difficulty": "medium"
                    }]
                })
            return "{}"

        mock_gen = MagicMock()
        mock_gen.chain.invoke.side_effect = mock_invoke

        with patch('routes.quiz.session_store', self.memory_store), \
             patch('routes.quiz.get_next_learning_action', return_value=self.adaptive_context), \
             patch('routes.quiz.Generator', return_value=mock_gen):
            resp = self.client.post(
                f'/api/quiz/generate/{self.session_id}',
                headers={'Authorization': 'Bearer test-token'},
                json={"count": 1, "concept": "Photosynthesis"}
            )

        self.assertEqual(resp.status_code, 200, f"Expected 200, got: {resp.data}")
        data = resp.get_json()
        self.assertEqual(len(data.get("mcq", [])), 1)
        self.assertEqual(data["mcq"][0]["question"], "Where does photosynthesis occur inside green plants?")
        self.assertEqual(len(data.get("short_answer", [])), 1)

    @patch('utils.auth.get_user_id_by_token', return_value=1)
    @patch('utils.auth.verify_session_owner', return_value=(True, 200))
    def test_unsupported_question_premise_rejected(self, mock_owner, mock_auth):
        """MCQ with question premise not grounded in source text must be rejected."""
        def mock_invoke(inputs):
            q_prompt = inputs.get("question", "")
            if "mcq" in q_prompt and "STUDY MATERIAL:" not in q_prompt:
                return json.dumps({
                    "mcq": [{
                        "question": "How many nuclear reactors power the chloroplast membrane?",
                        "options": ["1", "2", "3", "4"],
                        "answer": 0,
                        "difficulty": "medium",
                        "concept": "Photosynthesis"
                    }]
                })
            elif "STUDY MATERIAL:" in q_prompt:
                return json.dumps({
                    "valid": True,
                    "reason": "Nuclear reactors power chloroplasts",
                    "question_evidence": "Nuclear reactors power the chloroplast membrane.",
                    "answer_evidence": "Nuclear reactors power the chloroplast membrane."
                })
            return "{}"

        mock_gen = MagicMock()
        mock_gen.chain.invoke.side_effect = mock_invoke

        with patch('routes.quiz.session_store', self.memory_store), \
             patch('routes.quiz.get_next_learning_action', return_value=self.adaptive_context), \
             patch('routes.quiz.Generator', return_value=mock_gen):
            resp = self.client.post(
                f'/api/quiz/generate/{self.session_id}',
                headers={'Authorization': 'Bearer test-token'},
                json={"count": 1, "concept": "Photosynthesis"}
            )

        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("Insufficient novel questions generated for mcq", data["error"])

    @patch('utils.auth.get_user_id_by_token', return_value=1)
    @patch('utils.auth.verify_session_owner', return_value=(True, 200))
    def test_unsupported_correct_answer_rejected(self, mock_owner, mock_auth):
        """MCQ with correct answer evidence not found in source text must be rejected."""
        def mock_invoke(inputs):
            q_prompt = inputs.get("question", "")
            if "mcq" in q_prompt and "STUDY MATERIAL:" not in q_prompt:
                return json.dumps({
                    "mcq": [{
                        "question": "Where does photosynthesis occur inside green plants?",
                        "options": ["In the nucleus", "In ribosomes", "In lysosomes", "In centrioles"],
                        "answer": 0,
                        "difficulty": "medium",
                        "concept": "Photosynthesis"
                    }]
                })
            elif "STUDY MATERIAL:" in q_prompt:
                return json.dumps({
                    "valid": True,
                    "reason": "Answer evidence fabricated",
                    "question_evidence": "Photosynthesis occurs inside chloroplasts.",
                    "answer_evidence": "Photosynthesis takes place inside the nucleus."
                })
            return "{}"

        mock_gen = MagicMock()
        mock_gen.chain.invoke.side_effect = mock_invoke

        with patch('routes.quiz.session_store', self.memory_store), \
             patch('routes.quiz.get_next_learning_action', return_value=self.adaptive_context), \
             patch('routes.quiz.Generator', return_value=mock_gen):
            resp = self.client.post(
                f'/api/quiz/generate/{self.session_id}',
                headers={'Authorization': 'Bearer test-token'},
                json={"count": 1, "concept": "Photosynthesis"}
            )

        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("Insufficient novel questions generated for mcq", data["error"])

    @patch('utils.auth.get_user_id_by_token', return_value=1)
    @patch('utils.auth.verify_session_owner', return_value=(True, 200))
    def test_option_evidence_with_hallucinated_quote_rejected(self, mock_owner, mock_auth):
        """When option_evidence is provided, ungrounded option quote rejects question."""
        def mock_invoke(inputs):
            q_prompt = inputs.get("question", "")
            if "mcq" in q_prompt and "STUDY MATERIAL:" not in q_prompt:
                return json.dumps({
                    "mcq": [{
                        "question": "Where does photosynthesis occur inside green plants?",
                        "options": ["Inside chloroplasts", "In mitochondria"],
                        "answer": 0,
                        "difficulty": "medium",
                        "concept": "Photosynthesis"
                    }]
                })
            elif "STUDY MATERIAL:" in q_prompt:
                return json.dumps({
                    "valid": True,
                    "reason": "Validated",
                    "question_evidence": "Photosynthesis occurs inside chloroplasts.",
                    "answer_evidence": "Photosynthesis occurs inside chloroplasts.",
                    "option_evidence": {
                        "A": "Photosynthesis occurs inside chloroplasts.",
                        "B": "Mitochondria undergo quantum tunneling in plants."
                    }
                })
            return "{}"

        mock_gen = MagicMock()
        mock_gen.chain.invoke.side_effect = mock_invoke

        with patch('routes.quiz.session_store', self.memory_store), \
             patch('routes.quiz.get_next_learning_action', return_value=self.adaptive_context), \
             patch('routes.quiz.Generator', return_value=mock_gen):
            resp = self.client.post(
                f'/api/quiz/generate/{self.session_id}',
                headers={'Authorization': 'Bearer test-token'},
                json={"count": 1, "concept": "Photosynthesis"}
            )

        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("Insufficient novel questions generated for mcq", data["error"])

    @patch('utils.auth.get_user_id_by_token', return_value=1)
    @patch('utils.auth.verify_session_owner', return_value=(True, 200))
    def test_mcq_generation_honoring_requested_count(self, mock_owner, mock_auth):
        """MCQ generation requests bounded batches of 2 and accumulates 8 valid questions."""
        requested_batch_prompts = []
        q_counter = [0]
        sa_counter = [0]

        def mock_invoke(inputs):
            q_prompt = inputs.get("question", "")
            if "mcq" in q_prompt and "STUDY MATERIAL:" not in q_prompt:
                requested_batch_prompts.append(q_prompt)
                # Generate 2 distinct questions per batch
                batch = []
                for _ in range(2):
                    q_counter[0] += 1
                    idx = q_counter[0]
                    batch.append({
                        "question": f"Question number {idx}: Where does step {idx} occur in plants?",
                        "options": ["Inside chloroplasts", f"Option B{idx}", f"Option C{idx}", f"Option D{idx}"],
                        "answer": 0,
                        "difficulty": "medium",
                        "concept": "Photosynthesis",
                        "explanation": "Photosynthesis occurs inside chloroplasts."
                    })
                return json.dumps({"mcq": batch})
            elif "STUDY MATERIAL:" in q_prompt:
                return json.dumps({
                    "valid": True,
                    "reason": "Verified in source",
                    "question_evidence": "Photosynthesis occurs inside chloroplasts.",
                    "answer_evidence": "Photosynthesis occurs inside chloroplasts."
                })
            elif "short_answer" in q_prompt:
                import re
                m = re.search(r"Generate exactly (\d+) questions\.", q_prompt)
                b_size = int(m.group(1)) if m else 2
                sa_batch = []
                for _ in range(b_size):
                    sa_counter[0] += 1
                    sa_batch.append({
                        "question": f"Short answer question {sa_counter[0]} about chlorophyll",
                        "sample_answer": "Chlorophyll absorbs blue and red light",
                        "concept": "Photosynthesis",
                        "difficulty": "medium"
                    })
                return json.dumps({"short_answer": sa_batch})
            return "{}"

        mock_gen = MagicMock()
        mock_gen.chain.invoke.side_effect = mock_invoke

        with patch('routes.quiz.session_store', self.memory_store), \
             patch('routes.quiz.get_next_learning_action', return_value=self.adaptive_context), \
             patch('routes.quiz.Generator', return_value=mock_gen):
            resp = self.client.post(
                f'/api/quiz/generate/{self.session_id}',
                headers={'Authorization': 'Bearer test-token'},
                json={"count": 8, "concept": "Photosynthesis"}
            )

        self.assertEqual(resp.status_code, 200, f"Response error: {resp.data}")
        data = resp.get_json()

        # Each batch requested min(batch_size, remaining) = 2 questions
        self.assertTrue(all("Generate exactly 2 questions." in p for p in requested_batch_prompts))
        self.assertEqual(len(requested_batch_prompts), 4)  # 4 batches of 2 = 8

        self.assertEqual(len(data.get("mcq", [])), 8)
        self.assertEqual(len(data.get("short_answer", [])), 8)

    @patch('utils.auth.get_user_id_by_token', return_value=1)
    @patch('utils.auth.verify_session_owner', return_value=(True, 200))
    def test_final_partial_batch_size(self, mock_owner, mock_auth):
        """When requesting odd count (e.g. 3), final batch requests exactly remaining 1 question."""
        requested_batch_sizes = []
        counter = [0]

        def mock_invoke(inputs):
            q_prompt = inputs.get("question", "")
            if "mcq" in q_prompt and "STUDY MATERIAL:" not in q_prompt:
                # Detect the requested count in the prompt
                import re
                m = re.search(r"Generate exactly (\d+) questions\.", q_prompt)
                batch_count = int(m.group(1)) if m else 1
                requested_batch_sizes.append(batch_count)

                batch = []
                for _ in range(batch_count):
                    counter[0] += 1
                    batch.append({
                        "question": f"Odd question {counter[0]}: Where does reaction {counter[0]} occur?",
                        "options": ["Inside chloroplasts", "Opt B", "Opt C", "Opt D"],
                        "answer": 0,
                        "difficulty": "medium",
                        "concept": "Photosynthesis",
                        "explanation": "Photosynthesis occurs inside chloroplasts."
                    })
                return json.dumps({"mcq": batch})
            elif "STUDY MATERIAL:" in q_prompt:
                return json.dumps({
                    "valid": True,
                    "reason": "Verified in source",
                    "question_evidence": "Photosynthesis occurs inside chloroplasts.",
                    "answer_evidence": "Photosynthesis occurs inside chloroplasts."
                })
            elif "short_answer" in q_prompt:
                import re
                m = re.search(r"Generate exactly (\d+) questions\.", q_prompt)
                b_size = int(m.group(1)) if m else 1
                sa_batch = []
                for _ in range(b_size):
                    counter[0] += 1
                    sa_batch.append({
                        "question": f"SA Q{counter[0]}",
                        "sample_answer": "Chlorophyll absorbs blue and red light",
                        "concept": "Photosynthesis",
                        "difficulty": "medium"
                    })
                return json.dumps({"short_answer": sa_batch})
            return "{}"

        mock_gen = MagicMock()
        mock_gen.chain.invoke.side_effect = mock_invoke

        with patch('routes.quiz.session_store', self.memory_store), \
             patch('routes.quiz.get_next_learning_action', return_value=self.adaptive_context), \
             patch('routes.quiz.Generator', return_value=mock_gen):
            resp = self.client.post(
                f'/api/quiz/generate/{self.session_id}',
                headers={'Authorization': 'Bearer test-token'},
                json={"count": 3, "concept": "Photosynthesis"}
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data.get("mcq", [])), 3)
        # First batch asked for 2, second batch asked for 1
        self.assertEqual(requested_batch_sizes, [2, 1])

    @patch('utils.auth.get_user_id_by_token', return_value=1)
    @patch('utils.auth.verify_session_owner', return_value=(True, 200))
    def test_failed_batch_retains_valid_questions(self, mock_owner, mock_auth):
        """Failed batch (e.g. malformed JSON or exception) does not discard already accepted valid questions."""
        call_count = [0]
        counter = [0]

        def mock_invoke(inputs):
            q_prompt = inputs.get("question", "")
            if "mcq" in q_prompt and "STUDY MATERIAL:" not in q_prompt:
                call_count[0] += 1
                if call_count[0] == 2:
                    # Attempt 2 fails with malformed JSON / API error
                    raise ValueError("Groq API JSON parse error or network glitch")
                
                # Attempt 1 and 3 succeed with 2 valid questions each
                batch = []
                for _ in range(2):
                    counter[0] += 1
                    batch.append({
                        "question": f"Resilient question {counter[0]}: Where does step {counter[0]} happen?",
                        "options": ["Inside chloroplasts", "Opt B", "Opt C", "Opt D"],
                        "answer": 0,
                        "difficulty": "medium",
                        "concept": "Photosynthesis",
                        "explanation": "Photosynthesis occurs inside chloroplasts."
                    })
                return json.dumps({"mcq": batch})
            elif "STUDY MATERIAL:" in q_prompt:
                return json.dumps({
                    "valid": True,
                    "reason": "Verified in source",
                    "question_evidence": "Photosynthesis occurs inside chloroplasts.",
                    "answer_evidence": "Photosynthesis occurs inside chloroplasts."
                })
            elif "short_answer" in q_prompt:
                import re
                m = re.search(r"Generate exactly (\d+) questions\.", q_prompt)
                b_size = int(m.group(1)) if m else 2
                sa_batch = []
                for _ in range(b_size):
                    counter[0] += 1
                    sa_batch.append({
                        "question": f"SA step {counter[0]}",
                        "sample_answer": "Chlorophyll absorbs blue and red light",
                        "concept": "Photosynthesis",
                        "difficulty": "medium"
                    })
                return json.dumps({"short_answer": sa_batch})
            return "{}"

        mock_gen = MagicMock()
        mock_gen.chain.invoke.side_effect = mock_invoke

        with patch('routes.quiz.session_store', self.memory_store), \
             patch('routes.quiz.get_next_learning_action', return_value=self.adaptive_context), \
             patch('routes.quiz.Generator', return_value=mock_gen):
            resp = self.client.post(
                f'/api/quiz/generate/{self.session_id}',
                headers={'Authorization': 'Bearer test-token'},
                json={"count": 4, "concept": "Photosynthesis"}
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data.get("mcq", [])), 4)

    @patch('utils.auth.get_user_id_by_token', return_value=1)
    @patch('utils.auth.verify_session_owner', return_value=(True, 200))
    def test_invalid_duplicate_rejected_while_valid_retained(self, mock_owner, mock_auth):
        """Invalid or duplicate candidate in batch is rejected while valid question in same batch is retained."""
        counter = [0]

        def mock_invoke(inputs):
            q_prompt = inputs.get("question", "")
            if "mcq" in q_prompt and "STUDY MATERIAL:" not in q_prompt:
                counter[0] += 1
                # Return 1 valid novel question and 1 duplicate/ungrounded question
                return json.dumps({
                    "mcq": [
                        {
                            "question": f"Unique question {counter[0]}: Where does step {counter[0]} take place?",
                            "options": ["Inside chloroplasts", "Opt B", "Opt C", "Opt D"],
                            "answer": 0,
                            "difficulty": "medium",
                            "concept": "Photosynthesis",
                            "explanation": "Photosynthesis occurs inside chloroplasts."
                        },
                        {
                            # This question has ungrounded nuclear reactor premise
                            "question": f"Ungrounded question {counter[0]}: How many nuclear reactors in chloroplast?",
                            "options": ["1", "2", "3", "4"],
                            "answer": 0,
                            "difficulty": "medium",
                            "concept": "Photosynthesis",
                            "explanation": "Nuclear reactors power chloroplasts."
                        }
                    ]
                })
            elif "STUDY MATERIAL:" in q_prompt:
                if "nuclear reactors" in q_prompt:
                    return json.dumps({
                        "valid": False,
                        "reason": "Not in source",
                        "question_evidence": "",
                        "answer_evidence": ""
                    })
                return json.dumps({
                    "valid": True,
                    "reason": "Verified in source",
                    "question_evidence": "Photosynthesis occurs inside chloroplasts.",
                    "answer_evidence": "Photosynthesis occurs inside chloroplasts."
                })
            elif "short_answer" in q_prompt:
                import re
                m = re.search(r"Generate exactly (\d+) questions\.", q_prompt)
                b_size = int(m.group(1)) if m else 2
                sa_batch = []
                for _ in range(b_size):
                    counter[0] += 1
                    sa_batch.append({
                        "question": f"SA unique Q{counter[0]}",
                        "sample_answer": "Chlorophyll absorbs blue and red light",
                        "concept": "Photosynthesis",
                        "difficulty": "medium"
                    })
                return json.dumps({"short_answer": sa_batch})
            return "{}"

        mock_gen = MagicMock()
        mock_gen.chain.invoke.side_effect = mock_invoke

        with patch('routes.quiz.session_store', self.memory_store), \
             patch('routes.quiz.get_next_learning_action', return_value=self.adaptive_context), \
             patch('routes.quiz.Generator', return_value=mock_gen):
            resp = self.client.post(
                f'/api/quiz/generate/{self.session_id}',
                headers={'Authorization': 'Bearer test-token'},
                json={"count": 2, "concept": "Photosynthesis"}
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        # Successfully accumulated 2 valid questions across 2 attempts (1 per attempt)
        self.assertEqual(len(data.get("mcq", [])), 2)
        self.assertTrue(all("Unique question" in q["question"] for q in data["mcq"]))

    @patch('utils.auth.get_user_id_by_token', return_value=1)
    @patch('utils.auth.verify_session_owner', return_value=(True, 200))
    def test_rate_limit_error_aborts_immediately_without_retrying(self, mock_owner, mock_auth):
        """Simulated HTTP 429 / RateLimitError causes only one generator call, halts retries, and returns user-safe error."""
        call_count = [0]

        class FakeRateLimitError(Exception):
            status_code = 429

        def mock_invoke(inputs):
            call_count[0] += 1
            raise FakeRateLimitError("Rate limit reached for model openai/gpt-oss-20b: Limit 200000, Used 198465. 429 rate_limit_exceeded")

        mock_gen = MagicMock()
        mock_gen.chain.invoke.side_effect = mock_invoke

        with patch('routes.quiz.session_store', self.memory_store), \
             patch('routes.quiz.get_next_learning_action', return_value=self.adaptive_context), \
             patch('routes.quiz.Generator', return_value=mock_gen):
            resp = self.client.post(
                f'/api/quiz/generate/{self.session_id}',
                headers={'Authorization': 'Bearer test-token'},
                json={"count": 8, "concept": "Photosynthesis"}
            )

        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        expected_msg = "Quiz generation is temporarily unavailable because the AI provider's rate limit has been reached. Please try again later."
        self.assertEqual(data.get("error"), expected_msg)
        # Verify provider details, quota, or model names are not exposed
        self.assertNotIn("198465", data.get("error", ""))
        self.assertNotIn("openai/gpt-oss-20b", data.get("error", ""))
        # Verify retry loop stopped immediately on attempt 1 without continuing for 8 attempts
        self.assertEqual(call_count[0], 1)

    @patch('utils.auth.get_user_id_by_token', return_value=1)
    @patch('utils.auth.verify_session_owner', return_value=(True, 200))
    def test_adaptive_quiz_with_concept_none(self, mock_owner, mock_auth):
        """When concept is None in both plan and request, generation succeeds with fallback concept."""
        adaptive_context_no_concept = {
            "question_plan": {
                "difficulty": "easy",
                "target": "practice",
                "question_type": "conceptual",
                "reason": "General practice",
            },
            "action": "quiz",
        }

        def mock_invoke(inputs):
            q_prompt = inputs.get("question", "")
            if "mcq" in q_prompt and "STUDY MATERIAL:" not in q_prompt:
                return json.dumps({
                    "mcq": [{
                        "question": "Where does photosynthesis occur inside green plants?",
                        "options": ["Inside chloroplasts", "Respiration", "Digestion", "Excretion"],
                        "answer": 0,
                        "difficulty": "easy",
                        "concept": None,
                        "explanation": "Photosynthesis occurs inside chloroplasts."
                    }]
                })
            elif "STUDY MATERIAL:" in q_prompt:
                return json.dumps({
                    "valid": True,
                    "reason": "Directly supported",
                    "question_evidence": "Photosynthesis occurs inside chloroplasts.",
                    "answer_evidence": "Photosynthesis occurs inside chloroplasts."
                })
            elif "short_answer" in q_prompt:
                return json.dumps({
                    "short_answer": [{
                        "question": "Where does photosynthesis occur?",
                        "sample_answer": "In chloroplasts.",
                        "concept": None,
                        "difficulty": "easy"
                    }]
                })
            return "{}"

        mock_gen = MagicMock()
        mock_gen.chain.invoke.side_effect = mock_invoke

        with patch('routes.quiz.session_store', self.memory_store), \
             patch('routes.quiz.get_next_learning_action', return_value=adaptive_context_no_concept), \
             patch('routes.quiz.Generator', return_value=mock_gen):
            resp = self.client.post(
                f'/api/quiz/generate/{self.session_id}',
                headers={'Authorization': 'Bearer test-token'},
                json={"count": 1}
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data.get("mcq", [])), 1)
        # Verify fallback concept was assigned cleanly without ValueError
        self.assertTrue(bool(data["mcq"][0]["concept"]))
        self.assertEqual(len(data.get("short_answer", [])), 1)

    @patch('utils.auth.get_user_id_by_token', return_value=1)
    @patch('utils.auth.verify_session_owner', return_value=(True, 200))
    def test_five_question_hard_adaptive_quiz_flow(self, mock_owner, mock_auth):
        """Generates 5-question Hard adaptive quiz across multiple batches with context propagation."""
        adaptive_context_hard = {
            "question_plan": {
                "concept": "Calvin Cycle",
                "difficulty": "hard",
                "target": "mastery",
                "question_type": "analytical",
                "reason": "Test advanced enzymatic mechanisms"
            },
            "action": "quiz",
            "concept": "Calvin Cycle"
        }

        generated_questions_seen_in_prompts = []
        counter = [0]

        distinct_mcqs = [
            {
                "question": "Which specific enzyme fixes carbon dioxide into carbohydrates during the Calvin cycle?",
                "evidence": "Carbon dioxide is fixed into carbohydrates by the enzyme Rubisco.",
                "options": ["Rubisco", "ATP Synthase", "Helicase", "Polymerase"],
                "explanation": "Carbon dioxide is fixed into carbohydrates by the enzyme Rubisco."
            },
            {
                "question": "Which molecules are synthesized during light-dependent reactions to power the Calvin cycle?",
                "evidence": "During the light-dependent reactions, ATP and NADPH are synthesized to power the Calvin cycle.",
                "options": ["ATP and NADPH", "Glucose and Fructose", "DNA and RNA", "Lipids and Oils"],
                "explanation": "During the light-dependent reactions, ATP and NADPH are synthesized to power the Calvin cycle."
            },
            {
                "question": "How does chlorophyll interact with blue, red, and green light in plant leaves?",
                "evidence": "Chlorophyll absorbs blue and red light and reflects green light.",
                "options": ["Chlorophyll absorbs blue and red light and reflects green light.", "Opt B", "Opt C", "Opt D"],
                "explanation": "Chlorophyll absorbs blue and red light and reflects green light."
            },
            {
                "question": "Where does photosynthesis occur inside green plant cells?",
                "evidence": "Photosynthesis occurs inside chloroplasts.",
                "options": ["Inside chloroplasts", "In mitochondria", "In the cell wall", "In ribosomes"],
                "explanation": "Photosynthesis occurs inside chloroplasts."
            },
            {
                "question": "How do green plants synthesize nutrients through biological process?",
                "evidence": "Photosynthesis is the biological process by which green plants synthesize nutrients.",
                "options": ["Photosynthesis is the biological process by which green plants synthesize nutrients.", "B", "C", "D"],
                "explanation": "Photosynthesis is the biological process by which green plants synthesize nutrients."
            }
        ]

        distinct_sa = [
            {
                "question": "What end product is formed when carbon dioxide is fixed by Rubisco?",
                "evidence": "Carbon dioxide is fixed into carbohydrates by the enzyme Rubisco.",
                "sample_answer": "Carbon dioxide is fixed into carbohydrates by the enzyme Rubisco."
            },
            {
                "question": "Which chemical process produces ATP and NADPH before the Calvin cycle starts?",
                "evidence": "During the light-dependent reactions, ATP and NADPH are synthesized to power the Calvin cycle.",
                "sample_answer": "ATP and NADPH are synthesized to power the Calvin cycle."
            },
            {
                "question": "Which wavelengths or colors of light does chlorophyll absorb in plant leaves?",
                "evidence": "Chlorophyll absorbs blue and red light and reflects green light.",
                "sample_answer": "Chlorophyll absorbs blue and red light and reflects green light."
            },
            {
                "question": "Which primary enzyme catalyzes inorganic carbon assimilation into simple sugars?",
                "evidence": "Carbon dioxide is fixed into carbohydrates by the enzyme Rubisco.",
                "sample_answer": "Carbon dioxide is fixed into carbohydrates by the enzyme Rubisco."
            },
            {
                "question": "Why is light energy required in the initial phase of photosynthetic reactions?",
                "evidence": "During the light-dependent reactions, ATP and NADPH are synthesized to power the Calvin cycle.",
                "sample_answer": "ATP and NADPH are synthesized to power the Calvin cycle."
            }
        ]

        mcq_idx = [0]
        sa_idx = [0]

        def mock_invoke(inputs):
            q_prompt = inputs.get("question", "")
            if "mcq" in q_prompt and "STUDY MATERIAL:" not in q_prompt:
                # Capture prompt with accumulated context
                if "PREVIOUSLY ASKED QUESTIONS:" in q_prompt:
                    generated_questions_seen_in_prompts.append(q_prompt)

                import re
                m = re.search(r"Generate exactly (\d+) questions\.", q_prompt)
                batch_size = int(m.group(1)) if m else 2

                mcq_batch = []
                for _ in range(batch_size):
                    if mcq_idx[0] < len(distinct_mcqs):
                        item = distinct_mcqs[mcq_idx[0]]
                        mcq_idx[0] += 1
                        mcq_batch.append({
                            "question": item["question"],
                            "options": item["options"],
                            "answer": 0,
                            "difficulty": "hard",
                            "concept": "Calvin Cycle",
                            "explanation": item["explanation"]
                        })
                return json.dumps({"mcq": mcq_batch})

            elif "STUDY MATERIAL:" in q_prompt:
                for item in distinct_mcqs + distinct_sa:
                    if item["question"] in q_prompt:
                        return json.dumps({
                            "valid": True,
                            "reason": "Grounded in study text",
                            "question_evidence": item["evidence"],
                            "answer_evidence": item["evidence"]
                        })
                return json.dumps({
                    "valid": True,
                    "reason": "Default verified",
                    "question_evidence": "Photosynthesis occurs inside chloroplasts.",
                    "answer_evidence": "Photosynthesis occurs inside chloroplasts."
                })

            elif "short_answer" in q_prompt:
                import re
                m = re.search(r"Generate exactly (\d+) questions\.", q_prompt)
                batch_size = int(m.group(1)) if m else 2
                sa_batch = []
                for _ in range(batch_size):
                    if sa_idx[0] < len(distinct_sa):
                        item = distinct_sa[sa_idx[0]]
                        sa_idx[0] += 1
                        sa_batch.append({
                            "question": item["question"],
                            "sample_answer": item["sample_answer"],
                            "concept": "Calvin Cycle",
                            "difficulty": "hard"
                        })
                return json.dumps({"short_answer": sa_batch})

            return "{}"

        mock_gen = MagicMock()
        mock_gen.chain.invoke.side_effect = mock_invoke

        with patch('routes.quiz.session_store', self.memory_store), \
             patch('routes.quiz.get_next_learning_action', return_value=adaptive_context_hard), \
             patch('routes.quiz.Generator', return_value=mock_gen):
            resp = self.client.post(
                f'/api/quiz/generate/{self.session_id}',
                headers={'Authorization': 'Bearer test-token'},
                json={"count": 5, "concept": "Calvin Cycle"}
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        mcqs = data.get("mcq", [])
        short_answers = data.get("short_answer", [])

        # Exactly 5 questions generated and returned
        self.assertEqual(len(mcqs), 5)
        self.assertEqual(len(short_answers), 5)

        # All MCQs have difficulty "hard"
        for q in mcqs:
            self.assertEqual(q["difficulty"], "hard")

        # Verify that subsequent batches received previously generated questions in their prompt context
        self.assertTrue(len(generated_questions_seen_in_prompts) >= 2)
        later_prompt = generated_questions_seen_in_prompts[-1]
        self.assertIn(distinct_mcqs[0]["question"], later_prompt)

if __name__ == "__main__":
    unittest.main()
