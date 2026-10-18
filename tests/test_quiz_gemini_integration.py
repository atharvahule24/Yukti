import os
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import dotenv
dotenv.load_dotenv(WORKSPACE_ROOT / ".env")

from llm.gemini_generator import GeminiGenerator, GeminiError, GeminiRateLimitError
from routes.quiz import is_rate_limit_error, format_quiz_rate_limit_error


class TestQuizGeminiIntegration(unittest.TestCase):
    def setUp(self):
        self.mock_api_key = "test_gemini_key_12345"

    def test_gemini_generator_successful_invoke(self):
        """Verifies GeminiGenerator issues correct request structure, headers, and extracts response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": '{"mcq": [{"question": "What is photosynthesis?", "options": ["A", "B", "C", "D"], "answer": "A"}]}'}
                        ]
                    }
                }
            ]
        }

        with patch("requests.post", return_value=mock_response) as mock_post:
            generator = GeminiGenerator(json_mode=True, api_key=self.mock_api_key)
            result = generator.chain.invoke({
                "context": "Photosynthesis is the process by which plants make food.",
                "question": "Generate 1 MCQ."
            })

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            endpoint = call_args[0][0]
            headers = call_args[1]["headers"]
            payload = call_args[1]["json"]

            # Verify endpoint and model defaults to gemini-3.5-flash-lite
            self.assertEqual(generator.model_name, "gemini-3.5-flash-lite")
            self.assertIn("gemini-3.5-flash-lite:generateContent", endpoint)
            # Verify API key is passed securely via x-goog-api-key header, not in URL query string
            self.assertEqual(headers.get("x-goog-api-key"), self.mock_api_key)
            self.assertNotIn(self.mock_api_key, endpoint)
            # Verify JSON MIME type requested for structured output
            self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
            # Verify result content
            self.assertIn("What is photosynthesis?", result)

    def test_gemini_generator_missing_api_key(self):
        """Verifies GeminiGenerator raises explicit ValueError when QUIZ_GEMINI_API_KEY is missing."""
        with patch.dict(os.environ, {}, clear=True):
            generator = GeminiGenerator(json_mode=True, api_key=None)
            with self.assertRaises(ValueError) as ctx:
                generator.chain.invoke({"context": "text", "question": "question"})
            self.assertIn("QUIZ_GEMINI_API_KEY is not configured", str(ctx.exception))

    def test_gemini_generator_handles_http_429_rate_limit(self):
        """Verifies GeminiGenerator detects HTTP 429 and raises GeminiRateLimitError."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.json.return_value = {
            "error": {
                "code": 429,
                "message": "Resource has been exhausted (e.g. check quota). Please try again in 12.5s.",
                "status": "RESOURCE_EXHAUSTED"
            }
        }

        with patch("requests.post", return_value=mock_response):
            generator = GeminiGenerator(json_mode=True, api_key=self.mock_api_key)
            with self.assertRaises(GeminiRateLimitError) as ctx:
                generator.chain.invoke({"context": "text", "question": "question"})

            err = ctx.exception
            self.assertEqual(err.status_code, 429)
            self.assertTrue(is_rate_limit_error(err))
            formatted = format_quiz_rate_limit_error(err)
            self.assertIn("Quiz generation is temporarily unavailable", formatted)
            self.assertIn("12.5s", formatted)

    def test_gemini_generator_handles_resource_exhausted_403(self):
        """Verifies Gemini RESOURCE_EXHAUSTED on HTTP 403 maps to rate limit error."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "error": {
                "code": 403,
                "message": "Resource has been exhausted (check quota).",
                "status": "RESOURCE_EXHAUSTED"
            }
        }

        with patch("requests.post", return_value=mock_response):
            generator = GeminiGenerator(json_mode=True, api_key=self.mock_api_key)
            with self.assertRaises(GeminiRateLimitError) as ctx:
                generator.chain.invoke({"context": "text", "question": "question"})

            self.assertTrue(is_rate_limit_error(ctx.exception))

    def test_provider_isolation(self):
        """
        Verifies that Notes, Flashcards, Mind Map, and RAG Chat use Groq,
        while Quiz exclusively uses Google Gemini.
        """
        from llm.generator import Generator as GroqGenerator
        from routes.quiz import Generator as QuizGeneratorClass

        # 1. Quiz uses GeminiGenerator
        self.assertEqual(QuizGeneratorClass, GeminiGenerator)

        # 2. Notes and Flashcards use GroqGenerator
        from tasks import generate_notes_task, generate_flashcards_task
        # Both tasks instantiate Generator from llm.generator
        groq_gen = GroqGenerator(json_mode=True)
        # GroqGenerator model uses ChatGroq
        from langchain_groq import ChatGroq
        self.assertIsInstance(groq_gen.model, ChatGroq)

        # 3. Mind Map uses ChatGroq with GROQ_API_KEY
        from processing.graph_extractor import extract_knowledge_graph
        # Inspect module imports
        import processing.graph_extractor as ge
        self.assertEqual(ge.ChatGroq, ChatGroq)

        # 4. RAG Chat uses ChatGroq with GROQ_API_KEY
        from agents.rag_workflow import RagWorkflow
        with patch("agents.rag_workflow.VectorStore"), \
             patch("agents.rag_workflow.Embedder"):
            workflow = RagWorkflow()
            self.assertIsInstance(workflow.model, ChatGroq)

    def test_no_api_key_leakage_in_error_or_output(self):
        """Verifies secret API keys are never exposed in exception strings or logs."""
        secret_key = "AIzaSySecretApiKeyDoNotLeak999"
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal error on upstream server"
        mock_response.json.return_value = {"error": {"message": "Internal server error"}}

        with patch("requests.post", return_value=mock_response) as mock_post:
            generator = GeminiGenerator(json_mode=True, api_key=secret_key)
            with self.assertRaises(GeminiError) as ctx:
                generator.chain.invoke({"context": "text", "question": "question"})

            error_str = str(ctx.exception)
            self.assertNotIn(secret_key, error_str)

    def test_quiz_generate_endpoint_with_gemini(self):
        """Verifies /api/quiz/generate endpoint runs end-to-end with GeminiGenerator."""
        from app import app

        session_id = "test-gemini-quiz-sess"
        mock_session_data = {
            "session_id": session_id,
            "id": session_id,
            "user_id": 1,
            "filename": "biology.pdf",
            "full_text": "Photosynthesis is the process by which green plants synthesize nutrients from carbon dioxide and water.",
            "quiz_history": []
        }
        mock_store = {session_id: mock_session_data}

        adaptive_context = {
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

        mcq_payload = json.dumps({
            "mcq": [
                {
                    "question": "What raw materials are used in photosynthesis?",
                    "options": ["CO2 and H2O", "O2 and N2", "CO2 and CH4", "H2 and O2"],
                    "answer": 0,
                    "explanation": "Plants take in carbon dioxide and water to synthesize glucose.",
                    "difficulty": "medium",
                    "concept": "Photosynthesis"
                }
            ]
        })

        sa_payload = json.dumps({
            "short_answer": [
                {
                    "question": "Explain how plants synthesize nutrients during photosynthesis.",
                    "sample_answer": "Plants use carbon dioxide and water in the presence of sunlight to synthesize nutrients.",
                    "difficulty": "medium",
                    "concept": "Photosynthesis"
                }
            ]
        })

        validator_payload = json.dumps({
            "valid": True,
            "reason": "Directly mentioned in source text",
            "question_evidence": "Photosynthesis is the process by which green plants synthesize nutrients from carbon dioxide and water.",
            "answer_evidence": "Photosynthesis is the process by which green plants synthesize nutrients from carbon dioxide and water."
        })

        # Sequence of mocked responses: MCQ, MCQ validator, SA, SA validator
        responses = [mcq_payload, validator_payload, sa_payload, validator_payload]
        call_idx = [0]

        def mock_post(url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            current_text = responses[min(call_idx[0], len(responses) - 1)]
            call_idx[0] += 1
            resp.json.return_value = {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": current_text}]
                        }
                    }
                ]
            }
            return resp

        client = app.test_client()

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.quiz.get_next_learning_action", return_value=adaptive_context), \
             patch("routes.quiz.session_store", mock_store), \
             patch.dict(os.environ, {"QUIZ_GEMINI_API_KEY": "mock-gemini-key"}), \
             patch("requests.post", side_effect=mock_post):

            res = client.post(
                f"/api/quiz/generate/{session_id}",
                headers={"Authorization": "Bearer test-token"},
                json={"count": 1, "concept": "Photosynthesis"}
            )

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("mcq", data)
            self.assertIn("short_answer", data)
            self.assertEqual(len(data["mcq"]), 1)
            self.assertEqual(len(data["short_answer"]), 1)
            self.assertEqual(data["mcq"][0]["question"], "What raw materials are used in photosynthesis?")
            # Verify quiz was persisted in mock_store
            self.assertIn("quiz", mock_store[session_id])

    def test_quiz_generate_grounding_rejection_causes_400_when_retries_exhausted(self):
        """
        Verifies that when Gemini generates questions rejected by grounding validation,
        and retries are exhausted, the endpoint returns HTTP 400 with 'Insufficient novel questions generated'.
        """
        from app import app

        session_id = "test-gemini-rejected-quiz-sess"
        mock_session_data = {
            "session_id": session_id,
            "id": session_id,
            "user_id": 1,
            "filename": "biology.pdf",
            "full_text": "Photosynthesis is the process by which green plants synthesize nutrients from carbon dioxide and water.",
            "quiz_history": []
        }
        mock_store = {session_id: mock_session_data}

        adaptive_context = {
            "question_plan": {
                "concept": "Bleaching Powder",
                "difficulty": "medium",
                "target": "practice",
                "question_type": "conceptual",
                "reason": "Reinforce bleaching powder"
            },
            "action": "quiz",
            "concept": "Bleaching Powder"
        }

        mcq_payload = json.dumps({
            "mcq": [
                {
                    "question": "What is the formula for bleaching powder?",
                    "options": ["CaOCl2", "CaCO3", "CaSO4", "CaCl2"],
                    "answer": 0,
                    "explanation": "Bleaching powder is calcium oxychloride.",
                    "difficulty": "medium",
                    "concept": "Bleaching Powder"
                }
            ]
        })

        # Validator rejects because Bleaching Powder is not in the source text
        validator_rejected_payload = json.dumps({
            "valid": False,
            "reason": "Not mentioned in the study material",
            "question_evidence": "",
            "answer_evidence": ""
        })

        def mock_post(url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            req_json = kwargs.get("json", {})
            parts = req_json.get("contents", [{}])[0].get("parts", [{}])
            prompt_text = parts[0].get("text", "") if parts else ""
            if "STUDY MATERIAL:" in prompt_text:
                text = validator_rejected_payload
            else:
                text = mcq_payload

            resp.json.return_value = {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": text}]
                        }
                    }
                ]
            }
            return resp

        client = app.test_client()

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.quiz.get_next_learning_action", return_value=adaptive_context), \
             patch("routes.quiz.session_store", mock_store), \
             patch.dict(os.environ, {"QUIZ_GEMINI_API_KEY": "mock-gemini-key"}), \
             patch("requests.post", side_effect=mock_post):

            res = client.post(
                f"/api/quiz/generate/{session_id}",
                headers={"Authorization": "Bearer test-token"},
                json={"count": 1, "concept": "Bleaching Powder"}
            )

            self.assertEqual(res.status_code, 400)
            data = res.get_json()
            self.assertIn("error", data)
            self.assertIn("Insufficient novel questions generated for mcq", data["error"])

    def test_quiz_generate_long_document_relevant_context_succeeds(self):
        """
        Verifies that for long documents (>15,000 characters) where target concept
        is located beyond the legacy 3,000-character boundary, relevant context extraction
        provides the concept text to Gemini and validator, allowing generation to succeed (HTTP 200).
        """
        from app import app

        session_id = "test-long-doc-quiz-sess"
        long_full_text = (
            ("General background on chemistry and atoms. " * 350)
            + "\n\nBleaching powder is produced by the action of chlorine on dry slaked lime Ca(OH)2. The chemical formula for bleaching powder is CaOCl2.\n\n"
            + ("Further sections on acids and bases. " * 350)
        )
        mock_session_data = {
            "session_id": session_id,
            "id": session_id,
            "user_id": 1,
            "filename": "chemistry.pdf",
            "full_text": long_full_text,
            "quiz_history": []
        }
        mock_store = {session_id: mock_session_data}

        adaptive_context = {
            "question_plan": {
                "concept": "Bleaching Powder",
                "difficulty": "medium",
                "target": "practice",
                "question_type": "conceptual",
                "reason": "Reinforce bleaching powder"
            },
            "action": "quiz",
            "concept": "Bleaching Powder"
        }

        mcq_payload = json.dumps({
            "mcq": [
                {
                    "question": "What is the chemical formula for bleaching powder?",
                    "options": ["CaOCl2", "CaCO3", "CaSO4", "CaCl2"],
                    "answer": 0,
                    "explanation": "The chemical formula for bleaching powder is CaOCl2.",
                    "difficulty": "medium",
                    "concept": "Bleaching Powder"
                }
            ]
        })

        sa_payload = json.dumps({
            "short_answer": [
                {
                    "question": "How is bleaching powder produced?",
                    "sample_answer": "By the action of chlorine on dry slaked lime.",
                    "difficulty": "medium",
                    "concept": "Bleaching Powder"
                }
            ]
        })

        validator_payload = json.dumps({
            "valid": True,
            "reason": "Directly mentioned in the extracted source text",
            "question_evidence": "The chemical formula for bleaching powder is CaOCl2.",
            "answer_evidence": "The chemical formula for bleaching powder is CaOCl2."
        })

        captured_contexts = []

        responses = [mcq_payload, validator_payload, sa_payload, validator_payload]
        call_idx = [0]

        def mock_post(url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            req_json = kwargs.get("json", {})
            parts = req_json.get("contents", [{}])[0].get("parts", [{}])
            prompt_text = parts[0].get("text", "") if parts else ""
            captured_contexts.append(prompt_text)

            current_text = responses[min(call_idx[0], len(responses) - 1)]
            call_idx[0] += 1
            resp.json.return_value = {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": current_text}]
                        }
                    }
                ]
            }
            return resp

        client = app.test_client()

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.quiz.get_next_learning_action", return_value=adaptive_context), \
             patch("routes.quiz.session_store", mock_store), \
             patch.dict(os.environ, {"QUIZ_GEMINI_API_KEY": "mock-gemini-key"}), \
             patch("requests.post", side_effect=mock_post):

            res = client.post(
                f"/api/quiz/generate/{session_id}",
                headers={"Authorization": "Bearer test-token"},
                json={"count": 1, "concept": "Bleaching Powder"}
            )

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("mcq", data)
            self.assertIn("short_answer", data)
            self.assertEqual(len(data["mcq"]), 1)
            # Verify that the extracted context passed to Gemini contains the concept located at char 15000+
            self.assertTrue(any("Bleaching powder is produced" in ctx for ctx in captured_contexts))

    def test_quiz_generate_unsupported_adaptive_concept_fallback(self):
        """
        Verifies that when the adaptive plan proposes a concept unsupported by the document,
        the system safely falls back to core concepts from the material rather than forcing
        ungrounded questions and failing grounding validation.
        """
        from app import app

        session_id = "test-unsupported-concept-quiz-sess"
        mock_session_data = {
            "session_id": session_id,
            "id": session_id,
            "user_id": 1,
            "filename": "biology.pdf",
            "full_text": "Photosynthesis is the process by which green plants synthesize nutrients from carbon dioxide and water.",
            "quiz_history": []
        }
        mock_store = {session_id: mock_session_data}

        # Adaptive plan specifies an unsupported concept not present in biology.pdf
        adaptive_context = {
            "question_plan": {
                "concept": "Bleaching Powder",
                "difficulty": "medium",
                "target": "practice",
                "question_type": "conceptual",
                "reason": "Reinforce bleaching powder"
            },
            "action": "quiz",
            "concept": "Bleaching Powder"
        }

        mcq_payload = json.dumps({
            "mcq": [
                {
                    "question": "What is photosynthesis?",
                    "options": ["Nutrient synthesis", "Cell division", "Respiration", "Digestion"],
                    "answer": 0,
                    "explanation": "Photosynthesis is the process by which green plants synthesize nutrients.",
                    "difficulty": "medium",
                    "concept": "Photosynthesis"
                }
            ]
        })

        sa_payload = json.dumps({
            "short_answer": [
                {
                    "question": "Describe photosynthesis in green plants.",
                    "sample_answer": "Green plants synthesize nutrients from carbon dioxide and water.",
                    "difficulty": "medium",
                    "concept": "Photosynthesis"
                }
            ]
        })

        validator_payload = json.dumps({
            "valid": True,
            "reason": "Directly grounded in photosynthesis source text",
            "question_evidence": "Photosynthesis is the process by which green plants synthesize nutrients from carbon dioxide and water.",
            "answer_evidence": "Photosynthesis is the process by which green plants synthesize nutrients from carbon dioxide and water."
        })

        responses = [mcq_payload, validator_payload, sa_payload, validator_payload]
        call_idx = [0]

        def mock_post(url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            current_text = responses[min(call_idx[0], len(responses) - 1)]
            call_idx[0] += 1
            resp.json.return_value = {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": current_text}]
                        }
                    }
                ]
            }
            return resp

        client = app.test_client()

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.quiz.get_next_learning_action", return_value=adaptive_context), \
             patch("routes.quiz.session_store", mock_store), \
             patch.dict(os.environ, {"QUIZ_GEMINI_API_KEY": "mock-gemini-key"}), \
             patch("requests.post", side_effect=mock_post):

            res = client.post(
                f"/api/quiz/generate/{session_id}",
                headers={"Authorization": "Bearer test-token"},
                json={"count": 1, "concept": "Bleaching Powder"}
            )

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("mcq", data)
            self.assertIn("short_answer", data)
            self.assertEqual(len(data["mcq"]), 1)
            # The returned adaptive plan's concept should have safely fallen back rather than forcing the ungrounded concept
            self.assertIsNone(data["adaptive_plan"]["concept"])

    def test_quiz_submit_grades_and_persists_mcq_answers(self):
        """Verifies POST /api/quiz/submit/<session_id> grades against authoritative stored quiz and records score."""
        from flask import Flask
        from routes.quiz import quiz_bp

        app = Flask(__name__)
        app.register_blueprint(quiz_bp, url_prefix="/api")
        client = app.test_client()

        session_id = "test-submit-session-001"
        stored_quiz = {
            "mcq": [
                {
                    "id": "mcq_0",
                    "question": "What is the primary product of photosynthesis?",
                    "options": ["Oxygen and Glucose", "Nitrogen", "Methane", "Helium"],
                    "answer": 0,
                    "concept": "Photosynthesis"
                },
                {
                    "id": "mcq_1",
                    "question": "Which organelle conducts photosynthesis?",
                    "options": ["Mitochondria", "Ribosome", "Chloroplast", "Golgi"],
                    "answer": 2,
                    "concept": "Chloroplast"
                }
            ],
            "short_answer": []
        }
        mock_store = {
            session_id: {
                "id": session_id,
                "quiz": stored_quiz
            }
        }

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.quiz.session_store", mock_store), \
             patch("routes.quiz.record_quiz_score") as mock_record_score, \
             patch("routes.quiz.update_mastery_from_assessment") as mock_mastery:

            # Submit 1 correct answer (mcq_0=0) and 1 incorrect answer (mcq_1=0 instead of 2)
            res = client.post(
                f"/api/quiz/submit/{session_id}",
                headers={"Authorization": "Bearer test-token"},
                json={"answers": {"mcq_0": 0, "mcq_1": 0}}
            )

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["total_questions"], 2)
            self.assertEqual(data["correct_count"], 1)
            self.assertEqual(data["percentage"], 50.0)
            self.assertEqual(data["score"], 5.0)
            self.assertIn("details", data)
            self.assertEqual(len(data["details"]), 2)

            # Check that score was recorded in Supabase progress table
            mock_record_score.assert_called_once_with(session_id, 5.0)

            # Check that mastery updates were triggered for both concepts
            self.assertEqual(mock_mastery.call_count, 2)

            # Check that submission was persisted in session_store
            self.assertIn("quiz_submission", mock_store[session_id])
            self.assertEqual(mock_store[session_id]["quiz_submission"]["correct_count"], 1)

    def test_quiz_submit_idempotent_duplicate_prevented(self):
        """Verifies duplicate quiz submission returns existing result and does not increment quiz_attempts again."""
        from flask import Flask
        from routes.quiz import quiz_bp

        app = Flask(__name__)
        app.register_blueprint(quiz_bp, url_prefix="/api")
        client = app.test_client()

        session_id = "test-idempotent-session-002"
        existing_submission = {
            "score": 10.0,
            "percentage": 100.0,
            "correct_count": 2,
            "total_questions": 2,
            "answers": {"mcq_0": 0, "mcq_1": 2},
            "submitted_at": "2026-10-17T20:00:00Z"
        }
        mock_store = {
            session_id: {
                "id": session_id,
                "quiz": {
                    "mcq": [{"id": "mcq_0", "answer": 0}, {"id": "mcq_1", "answer": 2}]
                },
                "quiz_submission": existing_submission
            }
        }

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.quiz.session_store", mock_store), \
             patch("routes.quiz.record_quiz_score") as mock_record_score, \
             patch("routes.quiz.update_mastery_from_assessment") as mock_mastery:

            res = client.post(
                f"/api/quiz/submit/{session_id}",
                headers={"Authorization": "Bearer test-token"},
                json={"answers": {"mcq_0": 0, "mcq_1": 2}}
            )

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("already_submitted"))
            self.assertEqual(data["score"], 10.0)

            # Idempotency safeguard: record_quiz_score must NOT be called again
            mock_record_score.assert_not_called()
            mock_mastery.assert_not_called()

    def test_quiz_get_restores_submission_state(self):
        """Verifies GET /api/quiz/<session_id> restores saved submission state for page reloads."""
        from flask import Flask
        from routes.quiz import quiz_bp

        app = Flask(__name__)
        app.register_blueprint(quiz_bp, url_prefix="/api")
        client = app.test_client()

        session_id = "test-restore-session-003"
        mock_submission = {
            "score": 8.0,
            "percentage": 80.0,
            "correct_count": 4,
            "total_questions": 5,
            "answers": {"mcq_0": 0, "mcq_1": 1, "mcq_2": 2, "mcq_3": 3, "mcq_4": 0}
        }
        mock_store = {
            session_id: {
                "id": session_id,
                "quiz": {
                    "mcq": [{"id": f"mcq_{i}", "question": f"Q{i}", "options": ["A", "B"], "answer": 0} for i in range(5)],
                    "short_answer": []
                },
                "quiz_submission": mock_submission
            }
        }

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.quiz.session_store", mock_store):

            res = client.get(
                f"/api/quiz/{session_id}",
                headers={"Authorization": "Bearer test-token"}
            )

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(len(data["mcq"]), 5)
            self.assertIn("submission", data)
            self.assertEqual(data["submission"]["score"], 8.0)
            self.assertEqual(data["submission"]["correct_count"], 4)
            self.assertEqual(data["submission"]["answers"]["mcq_1"], 1)

    def test_short_answer_criterion_grading_incomplete_answer_not_full_marks(self):
        """
        Regression test: An answer addressing offspring characteristics but omitting
        long-term population effects must NOT receive full marks (10/10).
        """
        from routes.quiz import quiz_bp
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(quiz_bp, url_prefix="/api")
        client = app.test_client()

        session_id = "test-crit-incomplete-001"
        question = "Based on the provided text, analyze the contrasting outcomes of asexual reproduction involving a parent versus sexual reproduction involving two individuals with respect to offspring characteristics and their potential long-term effects on populations over generations."
        user_answer = "Asexual reproduction produces genetically similar offspring from one parent, while sexual reproduction combines genetic material from two parents and creates variation."
        sample_answer = "Asexual reproduction involves a single parent and produces genetically identical offspring. Sexual reproduction involves two parents and produces variable offspring. Over generations, genetic variation allows populations to adapt to changing environments and resist diseases, whereas asexual populations are more vulnerable to extinction."
        concept = "comparison of offspring characteristics and evolutionary effects"

        # Mock generator returns criterion-based grading response where offspring criterion is met, but population criterion is missing
        mock_ai_response = json.dumps({
            "criteria": [
                {
                    "criterion": "Contrast of offspring characteristics (asexual vs sexual reproduction)",
                    "max_points": 5.0,
                    "awarded_points": 5.0,
                    "status": "fully_met",
                    "evidence": "Asexual produces genetically similar offspring from one parent, while sexual reproduction combines genetic material from two parents and creates variation."
                },
                {
                    "criterion": "Potential long-term effects on populations over generations",
                    "max_points": 5.0,
                    "awarded_points": 0.0,
                    "status": "missing",
                    "evidence": "Not addressed"
                }
            ],
            "score": 5.0,
            "feedback": "You accurately analyzed offspring characteristics and genetic variation, but omitted long-term population effects over generations.",
            "correct_concepts": ["C1"],
            "missed_concepts": ["C1"],
            "study_tip": "Review how genetic variation in sexual reproduction aids long-term population adaptability over generations."
        })

        class MockChain:
            def invoke(self, *args, **kwargs):
                return mock_ai_response

        class MockGen:
            def __init__(self, *args, **kwargs):
                self.chain = MockChain()

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.quiz.validate_session_id", return_value=(True, None)), \
             patch("routes.quiz.Generator", MockGen), \
             patch("routes.quiz.record_quiz_score", return_value=None), \
             patch("routes.quiz.record_misconception", return_value=None), \
             patch("routes.quiz.optimize_learning_path", return_value={"action": "review", "reason": "Low mastery detected"}), \
             patch("routes.quiz.update_mastery_from_assessment", return_value={"score": 5.0, "correct": False}) as mock_update_mastery, \
             patch("routes.quiz.detect_misconception", return_value={"misconception": "incomplete_understanding", "severity": "low"}) as mock_detect_misc:

            res = client.post(
                "/api/quiz/grade",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "session_id": session_id,
                    "question": question,
                    "user_answer": user_answer,
                    "sample_answer": sample_answer,
                    "concept": concept,
                }
            )

            self.assertEqual(res.status_code, 200)
            data = res.get_json()

            # The incomplete answer must not receive full marks
            self.assertNotEqual(data["score"], 10.0)
            self.assertLess(data["score"], 7.0)
            self.assertEqual(data["score"], 5.0)

            # Criteria breakdown must be present and reflect the missing criterion
            self.assertIn("criteria", data)
            self.assertEqual(len(data["criteria"]), 2)
            c1, c2 = data["criteria"][0], data["criteria"][1]
            self.assertEqual(c1["status"], "fully_met")
            self.assertEqual(c1["awarded_points"], 5.0)
            self.assertEqual(c2["status"], "missing")
            self.assertEqual(c2["awarded_points"], 0.0)

            # Misconception detection should run for scores < 7
            mock_detect_misc.assert_called_once()
            # update_mastery_from_assessment must be called with correct=False for partial credit (< 7)
            mock_update_mastery.assert_called_once()
            call_kwargs = mock_update_mastery.call_args[1]
            self.assertFalse(call_kwargs["correct"])
            self.assertEqual(call_kwargs["score"], 5.0)

    def test_short_answer_criterion_grading_complete_answer_scores_higher(self):
        """
        Regression test: A complete answer addressing both criteria must score higher
        (e.g. 10.0/10) and mark assessment correct.
        """
        from routes.quiz import quiz_bp
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(quiz_bp, url_prefix="/api")
        client = app.test_client()

        session_id = "test-crit-complete-002"
        question = "Based on the provided text, analyze the contrasting outcomes of asexual reproduction involving a parent versus sexual reproduction involving two individuals with respect to offspring characteristics and their potential long-term effects on populations over generations."
        complete_answer = "Asexual reproduction involves one parent producing genetically identical offspring, which offers rapid reproduction but little genetic diversity, making populations vulnerable to disease or sudden environmental changes over generations. Sexual reproduction involves two parents combining genetic material to produce variable offspring, which promotes diversity and allows populations to adapt, survive environmental pressures, and evolve over generations."
        sample_answer = "Asexual reproduction involves a single parent and produces genetically identical offspring. Sexual reproduction involves two parents and produces variable offspring. Over generations, genetic variation allows populations to adapt to changing environments and resist diseases, whereas asexual populations are more vulnerable to extinction."
        concept = "comparison of offspring characteristics and evolutionary effects"

        mock_ai_response = json.dumps({
            "criteria": [
                {
                    "criterion": "Contrast of offspring characteristics (asexual vs sexual reproduction)",
                    "max_points": 5.0,
                    "awarded_points": 5.0,
                    "status": "fully_met",
                    "evidence": "Identical clones vs variable offspring."
                },
                {
                    "criterion": "Potential long-term effects on populations over generations",
                    "max_points": 5.0,
                    "awarded_points": 5.0,
                    "status": "fully_met",
                    "evidence": "Vulnerability to disease vs adaptability and survival over generations."
                }
            ],
            "score": 10.0,
            "feedback": "Comprehensive analysis addressing both offspring traits and long-term evolutionary impacts.",
            "correct_concepts": ["C1"],
            "missed_concepts": [],
            "study_tip": "Excellent work."
        })

        class MockChain:
            def invoke(self, *args, **kwargs):
                return mock_ai_response

        class MockGen:
            def __init__(self, *args, **kwargs):
                self.chain = MockChain()

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.quiz.validate_session_id", return_value=(True, None)), \
             patch("routes.quiz.Generator", MockGen), \
             patch("routes.quiz.record_quiz_score", return_value=None), \
             patch("routes.quiz.record_misconception", return_value=None), \
             patch("routes.quiz.optimize_learning_path", return_value={"action": "advance", "reason": "Strong mastery detected"}), \
             patch("routes.quiz.update_mastery_from_assessment", return_value={"score": 10.0, "correct": True}) as mock_update_mastery:

            res = client.post(
                "/api/quiz/grade",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "session_id": session_id,
                    "question": question,
                    "user_answer": complete_answer,
                    "sample_answer": sample_answer,
                    "concept": concept,
                }
            )

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["score"], 10.0)
            self.assertGreater(data["score"], 5.0)

            # update_mastery_from_assessment must be called with correct=True
            mock_update_mastery.assert_called_once()
            call_kwargs = mock_update_mastery.call_args[1]
            self.assertTrue(call_kwargs["correct"])
            self.assertEqual(call_kwargs["score"], 10.0)

    def test_short_answer_criterion_grading_irrelevant_answer_scores_low(self):
        """
        Regression test: An irrelevant answer must score low (0/10).
        """
        from routes.quiz import quiz_bp
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(quiz_bp, url_prefix="/api")
        client = app.test_client()

        session_id = "test-crit-irrelevant-003"
        question = "Based on the provided text, analyze the contrasting outcomes of asexual reproduction involving a parent versus sexual reproduction involving two individuals with respect to offspring characteristics and their potential long-term effects on populations over generations."
        irrelevant_answer = "Mitochondria are the powerhouse of the cell."
        sample_answer = "Asexual reproduction involves a single parent and produces genetically identical offspring..."
        concept = "comparison of offspring characteristics and evolutionary effects"

        mock_ai_response = json.dumps({
            "criteria": [
                {
                    "criterion": "Contrast of offspring characteristics (asexual vs sexual reproduction)",
                    "max_points": 5.0,
                    "awarded_points": 0.0,
                    "status": "missing",
                    "evidence": "Not addressed."
                },
                {
                    "criterion": "Potential long-term effects on populations over generations",
                    "max_points": 5.0,
                    "awarded_points": 0.0,
                    "status": "missing",
                    "evidence": "Not addressed."
                }
            ],
            "score": 0.0,
            "feedback": "Your answer is completely unrelated to the question.",
            "correct_concepts": [],
            "missed_concepts": ["C1"],
            "study_tip": "Review asexual and sexual reproduction concepts."
        })

        class MockChain:
            def invoke(self, *args, **kwargs):
                return mock_ai_response

        class MockGen:
            def __init__(self, *args, **kwargs):
                self.chain = MockChain()

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.quiz.validate_session_id", return_value=(True, None)), \
             patch("routes.quiz.Generator", MockGen), \
             patch("routes.quiz.record_quiz_score", return_value=None), \
             patch("routes.quiz.record_misconception", return_value=None), \
             patch("routes.quiz.optimize_learning_path", return_value={"action": "review", "reason": "Low mastery detected"}), \
             patch("routes.quiz.detect_misconception", return_value={"misconception": "unrelated", "severity": "high"}), \
             patch("routes.quiz.update_mastery_from_assessment", return_value={"score": 0.0, "correct": False}) as mock_update_mastery:

            res = client.post(
                "/api/quiz/grade",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "session_id": session_id,
                    "question": question,
                    "user_answer": irrelevant_answer,
                    "sample_answer": sample_answer,
                    "concept": concept,
                }
            )

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["score"], 0.0)
            mock_update_mastery.assert_called_once()
            call_kwargs = mock_update_mastery.call_args[1]
            self.assertFalse(call_kwargs["correct"])

    def test_short_answer_criteria_score_deterministic_enforcement(self):
        """
        Regression test: If the raw AI output claims score: 10, but the criteria evaluation
        shows a missing criterion (or student answer lacks the required component), the backend
        deterministically enforces the criteria calculation and overrides score to 5.0.
        """
        from routes.quiz import quiz_bp
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(quiz_bp, url_prefix="/api")
        client = app.test_client()

        session_id = "test-crit-override-004"
        question = "Based on the provided text, analyze the contrasting outcomes of asexual reproduction involving a parent versus sexual reproduction involving two individuals with respect to offspring characteristics and their potential long-term effects on populations over generations."
        user_answer = "Asexual reproduction produces genetically similar offspring from one parent, while sexual reproduction combines genetic material from two parents and creates variation."
        concept = "comparison of offspring characteristics and evolutionary effects"

        # Simulate buggy AI returning holistic score: 10 despite missing population criterion
        buggy_ai_response = json.dumps({
            "criteria": [
                {
                    "criterion": "Contrast of offspring characteristics (asexual vs sexual reproduction)",
                    "max_points": 5.0,
                    "awarded_points": 5.0,
                    "status": "fully_met",
                    "evidence": "Offspring characteristics stated."
                },
                {
                    "criterion": "Potential long-term effects on populations over generations",
                    "max_points": 5.0,
                    "awarded_points": 0.0,
                    "status": "missing",
                    "evidence": "Not addressed in the answer."
                }
            ],
            "score": 10.0,  # Buggy raw score
            "feedback": "Missing long term effects",
            "correct_concepts": ["C1"],
            "missed_concepts": ["C1"]
        })

        class MockChain:
            def invoke(self, *args, **kwargs):
                return buggy_ai_response

        class MockGen:
            def __init__(self, *args, **kwargs):
                self.chain = MockChain()

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.quiz.validate_session_id", return_value=(True, None)), \
             patch("routes.quiz.Generator", MockGen), \
             patch("routes.quiz.record_quiz_score", return_value=None), \
             patch("routes.quiz.record_misconception", return_value=None), \
             patch("routes.quiz.optimize_learning_path", return_value={"action": "review", "reason": "Low mastery detected"}), \
             patch("routes.quiz.detect_misconception", return_value={"misconception": "incomplete_understanding", "severity": "low"}), \
             patch("routes.quiz.update_mastery_from_assessment", return_value={"score": 5.0, "correct": False}) as mock_update_mastery:

            res = client.post(
                "/api/quiz/grade",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "session_id": session_id,
                    "question": question,
                    "user_answer": user_answer,
                    "concept": concept,
                }
            )

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            # Backend calculation must override the 10.0 score to 5.0
            self.assertEqual(data["score"], 5.0)
            mock_update_mastery.assert_called_once()
            self.assertFalse(mock_update_mastery.call_args[1]["correct"])

    def test_short_answer_correct_paraphrase_without_rubric_keywords(self):
        """
        Regression test: An answer providing a valid, scientifically sound paraphrase without
        repeating literal rubric keywords must receive full marks (10.0/10).
        """
        from routes.quiz import quiz_bp
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(quiz_bp, url_prefix="/api")
        client = app.test_client()

        session_id = "test-crit-paraphrase-005"
        question = "Based on the provided text, analyze the contrasting outcomes of asexual reproduction involving a parent versus sexual reproduction involving two individuals with respect to offspring characteristics and their potential long-term effects on populations over generations."
        paraphrase_answer = "Single-parent propagation yields carbon-copy progeny, whereas biparental union blends inherited traits to foster diversity. Across centuries and ages, this variety empowers biological communities to withstand shifting climates and novel pathogens, whereas uniform lineages risk extinction under environmental stress."
        concept = "comparison of offspring characteristics and evolutionary effects"

        mock_ai_response = json.dumps({
            "criteria": [
                {
                    "criterion": "Offspring characteristics",
                    "max_points": 5.0,
                    "awarded_points": 5.0,
                    "status": "fully_met",
                    "evidence": "Single-parent propagation yields carbon-copy progeny, whereas biparental union blends inherited traits to foster diversity."
                },
                {
                    "criterion": "Potential long-term effects on populations over generations",
                    "max_points": 5.0,
                    "awarded_points": 5.0,
                    "status": "fully_met",
                    "evidence": "Across centuries and ages, this variety empowers biological communities to withstand shifting climates and novel pathogens..."
                }
            ],
            "score": 10.0,
            "feedback": "Outstanding paraphrase analyzing both offspring uniformity/diversity and long-term population adaptability.",
            "correct_concepts": ["C1"],
            "missed_concepts": [],
            "study_tip": "Keep up the excellent analytical work."
        })

        class MockChain:
            def invoke(self, *args, **kwargs):
                return mock_ai_response

        class MockGen:
            def __init__(self, *args, **kwargs):
                self.chain = MockChain()

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.quiz.validate_session_id", return_value=(True, None)), \
             patch("routes.quiz.Generator", MockGen), \
             patch("routes.quiz.record_quiz_score", return_value=None), \
             patch("routes.quiz.record_misconception", return_value=None), \
             patch("routes.quiz.optimize_learning_path", return_value={"action": "advance", "reason": "Strong mastery detected"}), \
             patch("routes.quiz.update_mastery_from_assessment", return_value={"score": 10.0, "correct": True}) as mock_update_mastery:

            res = client.post(
                "/api/quiz/grade",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "session_id": session_id,
                    "question": question,
                    "user_answer": paraphrase_answer,
                    "concept": concept,
                }
            )

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["score"], 10.0)
            self.assertEqual(len(data["criteria"]), 2)
            self.assertEqual(data["criteria"][0]["status"], "fully_met")
            self.assertEqual(data["criteria"][1]["status"], "fully_met")
            mock_update_mastery.assert_called_once()
            self.assertTrue(mock_update_mastery.call_args[1]["correct"])

    def test_short_answer_unrelated_to_reproduction(self):
        """
        Regression test: Questions in non-biology domains (e.g. History/Economics)
        extract criteria cleanly and evaluate partial scores properly when one criterion is missed.
        """
        from routes.quiz import quiz_bp
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(quiz_bp, url_prefix="/api")
        client = app.test_client()

        session_id = "test-crit-history-006"
        question = "Analyze the French Revolution with respect to economic causes and political transformations."
        user_answer = "The economic causes were high taxation on the Third Estate, food shortages, and national debt from foreign wars."
        concept = "French Revolution"

        mock_ai_response = json.dumps({
            "criteria": [
                {
                    "criterion": "Economic causes",
                    "max_points": 5.0,
                    "awarded_points": 5.0,
                    "status": "fully_met",
                    "evidence": "High taxation on the Third Estate, food shortages, and national debt."
                },
                {
                    "criterion": "Political transformations",
                    "max_points": 5.0,
                    "awarded_points": 0.0,
                    "status": "missing",
                    "evidence": "Not addressed in the answer."
                }
            ],
            "score": 5.0,
            "feedback": "You clearly explained the financial and agricultural crises, but did not address the political restructuring.",
            "correct_concepts": ["C1"],
            "missed_concepts": ["C1"]
        })

        class MockChain:
            def invoke(self, *args, **kwargs):
                return mock_ai_response

        class MockGen:
            def __init__(self, *args, **kwargs):
                self.chain = MockChain()

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.quiz.validate_session_id", return_value=(True, None)), \
             patch("routes.quiz.Generator", MockGen), \
             patch("routes.quiz.record_quiz_score", return_value=None), \
             patch("routes.quiz.record_misconception", return_value=None), \
             patch("routes.quiz.optimize_learning_path", return_value={"action": "review", "reason": "Low mastery detected"}), \
             patch("routes.quiz.detect_misconception", return_value={"misconception": "incomplete_understanding", "severity": "low"}), \
             patch("routes.quiz.update_mastery_from_assessment", return_value={"score": 5.0, "correct": False}) as mock_update_mastery:

            res = client.post(
                "/api/quiz/grade",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "session_id": session_id,
                    "question": question,
                    "user_answer": user_answer,
                    "concept": concept,
                }
            )

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["score"], 5.0)
            self.assertEqual(len(data["criteria"]), 2)
            self.assertEqual(data["criteria"][0]["criterion"], "Economic causes")
            self.assertEqual(data["criteria"][0]["awarded_points"], 5.0)
            self.assertEqual(data["criteria"][1]["criterion"], "Political transformations")
            self.assertEqual(data["criteria"][1]["awarded_points"], 0.0)
            mock_update_mastery.assert_called_once()
            self.assertFalse(mock_update_mastery.call_args[1]["correct"])

    def test_short_answer_more_than_two_criteria_and_explicit_criteria(self):
        """
        Regression test: Questions with 3+ criteria and explicit criteria provided by caller
        are evaluated with proportional point weights and calculate correct score.
        """
        from routes.quiz import quiz_bp
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(quiz_bp, url_prefix="/api")
        client = app.test_client()

        session_id = "test-crit-multi-007"
        question = "Compare series and parallel circuits in terms of current flow, voltage distribution across components, and effect of component failure."
        user_answer = "In a series circuit, current is identical everywhere and voltage divides across resistors. In a parallel circuit, total current divides across branches and each branch receives full supply voltage."
        concept = "Electric Circuits"

        explicit_criteria = [
            {"criterion": "Current flow differences", "max_points": 3.0},
            {"criterion": "Voltage distribution differences", "max_points": 3.0},
            {"criterion": "Effect of component failure", "max_points": 4.0}
        ]

        # Student answered criteria 1 and 2, but omitted criterion 3 (effect of component failure)
        mock_ai_response = json.dumps({
            "criteria": [
                {
                    "criterion": "Current flow differences",
                    "max_points": 3.0,
                    "awarded_points": 3.0,
                    "status": "fully_met",
                    "evidence": "Series current identical, parallel current divides."
                },
                {
                    "criterion": "Voltage distribution differences",
                    "max_points": 3.0,
                    "awarded_points": 3.0,
                    "status": "fully_met",
                    "evidence": "Series voltage divides, parallel receives full supply voltage."
                },
                {
                    "criterion": "Effect of component failure",
                    "max_points": 4.0,
                    "awarded_points": 0.0,
                    "status": "missing",
                    "evidence": "Omitted. Did not explain what happens when one component breaks."
                }
            ],
            "score": 6.0,
            "feedback": "You answered current and voltage correctly, but did not explain what happens when a component fails.",
            "correct_concepts": ["C1"],
            "missed_concepts": ["C1"]
        })

        class MockChain:
            def invoke(self, *args, **kwargs):
                return mock_ai_response

        class MockGen:
            def __init__(self, *args, **kwargs):
                self.chain = MockChain()

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.quiz.validate_session_id", return_value=(True, None)), \
             patch("routes.quiz.Generator", MockGen), \
             patch("routes.quiz.record_quiz_score", return_value=None), \
             patch("routes.quiz.record_misconception", return_value=None), \
             patch("routes.quiz.optimize_learning_path", return_value={"action": "practice", "reason": "Partial mastery"}), \
             patch("routes.quiz.detect_misconception", return_value={"misconception": "incomplete_understanding", "severity": "low"}), \
             patch("routes.quiz.update_mastery_from_assessment", return_value={"score": 6.0, "correct": False}) as mock_update_mastery:

            res = client.post(
                "/api/quiz/grade",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "session_id": session_id,
                    "question": question,
                    "user_answer": user_answer,
                    "concept": concept,
                    "criteria": explicit_criteria,
                }
            )

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["score"], 6.0)
            self.assertEqual(len(data["criteria"]), 3)
            self.assertEqual(data["criteria"][0]["awarded_points"], 3.0)
            self.assertEqual(data["criteria"][1]["awarded_points"], 3.0)
            self.assertEqual(data["criteria"][2]["awarded_points"], 0.0)
            self.assertEqual(data["criteria"][2]["status"], "missing")
            mock_update_mastery.assert_called_once()
            self.assertFalse(mock_update_mastery.call_args[1]["correct"])


if __name__ == "__main__":
    unittest.main()
