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


if __name__ == "__main__":
    unittest.main()
