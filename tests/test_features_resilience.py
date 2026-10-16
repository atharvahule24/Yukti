import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from tasks import (
    generate_graph_task,
    generate_flashcards_task,
    normalize_and_validate_flashcards,
)
from routes.quiz import is_rate_limit_error, format_quiz_rate_limit_error


class TestFeaturesResilience(unittest.TestCase):
    def setUp(self):
        self.session_id = "test-resilience-session-123"
        self.memory_store = {
            self.session_id: {
                "id": self.session_id,
                "title": "Test Title",
                "full_text": "This is sample document text covering key concepts and terms for education.",
                "graph": None,
                "flashcards": None,
            }
        }

    # ------------------ FLASHCARDS TESTS ------------------

    def test_normalize_flashcards_various_shapes(self):
        # 1. Standard {"cards": [...]}
        raw1 = {
            "cards": [
                {"front": "What is ATP?", "back": "Energy currency of cell", "explanation": "Adenosine triphosphate", "hint": "Energy"}
            ]
        }
        res1 = normalize_and_validate_flashcards(raw1)
        self.assertEqual(len(res1["cards"]), 1)
        self.assertEqual(res1["cards"][0]["front"], "What is ATP?")
        self.assertEqual(res1["cards"][0]["id"], "card_0")

        # 2. Alternative {"flashcards": [...]} with question/answer keys
        raw2 = {
            "flashcards": [
                {"question": "What is DNA?", "answer": "Genetic material"}
            ]
        }
        res2 = normalize_and_validate_flashcards(raw2)
        self.assertEqual(len(res2["cards"]), 1)
        self.assertEqual(res2["cards"][0]["front"], "What is DNA?")
        self.assertEqual(res2["cards"][0]["back"], "Genetic material")

        # 3. Raw list
        raw3 = [
            {"front": "Term", "back": "Definition"}
        ]
        res3 = normalize_and_validate_flashcards(raw3)
        self.assertEqual(len(res3["cards"]), 1)

    def test_normalize_flashcards_empty_or_invalid_raises(self):
        with self.assertRaises(ValueError):
            normalize_and_validate_flashcards({})

        with self.assertRaises(ValueError):
            normalize_and_validate_flashcards({"cards": []})

        with self.assertRaises(ValueError):
            normalize_and_validate_flashcards("not a dict")

        with self.assertRaises(ValueError):
            normalize_and_validate_flashcards({"cards": [{"front": "", "back": ""}]})

    def test_generate_flashcards_task_http_429_handling(self):
        err_msg = (
            "Error code: 429 - {'error': {'message': 'Rate limit reached for model openai/gpt-oss-20b "
            "in organization org_123 on tokens per day (TPD): Limit 200000, Used 198400, Requested 1872. "
            "Please try again in 5m22.400s.'}}"
        )
        with patch("tasks.session_store", self.memory_store), \
             patch.object(generate_flashcards_task, "update_state"), \
             patch("llm.generator.Generator") as mock_gen_cls:
            mock_gen = MagicMock()
            mock_gen.chain.invoke.side_effect = Exception(err_msg)
            mock_gen_cls.return_value = mock_gen

            with self.assertRaises(RuntimeError) as ctx:
                generate_flashcards_task.run(self.session_id)

            self.assertIn("Groq API rate limit reached", str(ctx.exception))
            self.assertIn("5m22.400s", str(ctx.exception))

    def test_generate_flashcards_task_fails_explicitly_on_empty_extraction(self):
        with patch("tasks.session_store", self.memory_store), \
             patch.object(generate_flashcards_task, "update_state"), \
             patch("llm.generator.Generator") as mock_gen_cls:
            mock_gen = MagicMock()
            mock_gen.chain.invoke.return_value = '{"cards": []}'
            mock_gen_cls.return_value = mock_gen

            with self.assertRaises(ValueError):
                generate_flashcards_task.run(self.session_id)

    def test_generate_flashcards_task_preserves_existing_cards_on_failure(self):
        existing_cards = {
            "cards": [{"id": "card_0", "front": "Existing Front", "back": "Existing Back"}]
        }
        self.memory_store[self.session_id]["flashcards"] = existing_cards

        with patch("tasks.session_store", self.memory_store), \
             patch.object(generate_flashcards_task, "update_state"), \
             patch("llm.generator.Generator") as mock_gen_cls:
            mock_gen = MagicMock()
            mock_gen.chain.invoke.return_value = "Non-json output"
            mock_gen_cls.return_value = mock_gen

            result = generate_flashcards_task.run(self.session_id)
            self.assertEqual(result, existing_cards)
            self.assertEqual(self.memory_store[self.session_id]["flashcards"], existing_cards)

    # ------------------ MIND MAP (GRAPH) TESTS ------------------

    def test_generate_graph_task_fails_explicitly_on_empty_extraction(self):
        with patch("tasks.session_store", self.memory_store), \
             patch.object(generate_graph_task, "update_state"), \
             patch("processing.graph_extractor.extract_knowledge_graph", return_value={"nodes": [], "edges": [], "links": []}):

            with self.assertRaises(ValueError) as ctx:
                generate_graph_task.run(self.session_id, force=True)

            self.assertIn("Failed to extract a valid knowledge graph", str(ctx.exception))

    def test_generate_graph_task_handles_http_429_rate_limit(self):
        err_msg = "Error code: 429 - tokens per day (TPD) exceeded. Please try again in 3m15s."
        with patch("tasks.session_store", self.memory_store), \
             patch.object(generate_graph_task, "update_state"), \
             patch("processing.graph_extractor.extract_knowledge_graph", side_effect=Exception(err_msg)):

            with self.assertRaises(RuntimeError) as ctx:
                generate_graph_task.run(self.session_id, force=True)

            self.assertIn("Groq API rate limit reached", str(ctx.exception))
            self.assertIn("3m15s", str(ctx.exception))

    def test_generate_graph_task_preserves_valid_graph_on_invalid_output(self):
        existing_graph = {
            "nodes": [{"id": "n1", "label": "Node 1", "subject": "Bio"}, {"id": "n2", "label": "Node 2", "subject": "Bio"}],
            "links": [{"source": "n1", "target": "n2", "label": "includes"}]
        }
        self.memory_store[self.session_id]["graph"] = existing_graph

        with patch("tasks.session_store", self.memory_store), \
             patch.object(generate_graph_task, "update_state"), \
             patch("processing.graph_extractor.extract_knowledge_graph", return_value={"nodes": [], "edges": []}):

            result = generate_graph_task.run(self.session_id, force=True)
            self.assertEqual(result, existing_graph)
            self.assertEqual(self.memory_store[self.session_id]["graph"], existing_graph)

    # ------------------ QUIZ RATE LIMIT TESTS ------------------

    def test_quiz_rate_limit_detection_and_formatting(self):
        exc_with_cooldown = Exception("429 rate_limit_exceeded: Please try again in 4m10.200s.")
        self.assertTrue(is_rate_limit_error(exc_with_cooldown))
        formatted = format_quiz_rate_limit_error(exc_with_cooldown)
        self.assertIn("Quiz generation is temporarily unavailable", formatted)
        self.assertIn("4m10.200s", formatted)

        exc_generic_429 = Exception("RateLimitError: 429 Too Many Requests")
        self.assertTrue(is_rate_limit_error(exc_generic_429))
        formatted_generic = format_quiz_rate_limit_error(exc_generic_429)
        self.assertIn("Please try again later.", formatted_generic)


if __name__ == "__main__":
    unittest.main()
