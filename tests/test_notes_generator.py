import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import dotenv
dotenv.load_dotenv(WORKSPACE_ROOT / ".env")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy-service-key")
os.environ.setdefault("GROQ_API_KEY", "mock-groq-key")

from tasks import normalize_and_validate_notes, generate_notes_task


class TestNotesGenerator(unittest.TestCase):
    def test_normalize_and_validate_notes_standard_points(self):
        """Standard {"points": [...]} returns properly formatted notes."""
        raw = {
            "points": [
                {
                    "bullet": "Concept A",
                    "explanation": "Explanation for concept A.",
                    "example": "Example A",
                    "importance": "high"
                }
            ]
        }
        res = normalize_and_validate_notes(raw)
        self.assertIn("points", res)
        self.assertEqual(len(res["points"]), 1)
        self.assertEqual(res["points"][0]["bullet"], "Concept A")
        self.assertEqual(res["points"][0]["explanation"], "Explanation for concept A.")
        self.assertEqual(res["points"][0]["importance"], "high")

    def test_normalize_and_validate_notes_alternative_keys(self):
        """Alternative keys (notes, key_concepts, cards, or raw list) are normalized."""
        # 1. key_concepts
        res_kc = normalize_and_validate_notes({
            "key_concepts": [{"bullet": "KC1", "explanation": "Explanation KC1"}]
        })
        self.assertEqual(len(res_kc["points"]), 1)
        self.assertEqual(res_kc["points"][0]["bullet"], "KC1")

        # 2. notes
        res_notes = normalize_and_validate_notes({
            "notes": [{"title": "Note1", "description": "Desc1"}]
        })
        self.assertEqual(len(res_notes["points"]), 1)
        self.assertEqual(res_notes["points"][0]["bullet"], "Note1")
        self.assertEqual(res_notes["points"][0]["explanation"], "Desc1")

        # 3. raw list
        res_list = normalize_and_validate_notes([
            {"concept": "Raw1", "content": "Raw content 1"}
        ])
        self.assertEqual(len(res_list["points"]), 1)
        self.assertEqual(res_list["points"][0]["bullet"], "Raw1")

    def test_normalize_and_validate_notes_empty_or_invalid_raises(self):
        """Empty lists, empty dicts, or unparseable input raise ValueError."""
        with self.assertRaises(ValueError):
            normalize_and_validate_notes({})

        with self.assertRaises(ValueError):
            normalize_and_validate_notes({"points": []})

        with self.assertRaises(ValueError):
            normalize_and_validate_notes("not a dict or list")

        with self.assertRaises(ValueError):
            normalize_and_validate_notes([{"bullet": "", "explanation": ""}])

    @patch("tasks.session_store")
    @patch("llm.generator.Generator")
    def test_generate_notes_task_handles_http_429_rate_limit(self, mock_generator_cls, mock_store):
        """Groq 429 rate limit is captured and raises clear RuntimeError with cooldown information."""
        mock_store.get.return_value = {
            "id": "sess-429",
            "full_text": "Sample lecture text for rate limit test.",
        }

        mock_gen_instance = MagicMock()
        mock_gen_instance.chain.invoke.side_effect = Exception(
            "Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-20b` "
            "on tokens per day (TPD): Limit 200000, Used 198400, Requested 1872. Please try again in 1m57.504s.', "
            "'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
        )
        mock_generator_cls.return_value = mock_gen_instance

        with patch.object(generate_notes_task, "update_state"):
            with self.assertRaises(RuntimeError) as ctx:
                generate_notes_task.run("sess-429")

        self.assertIn("Groq API rate limit reached", str(ctx.exception))
        self.assertIn("Please try again in 1m57", str(ctx.exception))

    @patch("tasks.session_store")
    @patch("llm.generator.Generator")
    def test_generate_notes_task_fails_explicitly_on_empty_extraction(self, mock_generator_cls, mock_store):
        """New sessions with invalid/empty LLM responses raise ValueError instead of returning empty success."""
        mock_store.get.return_value = {
            "id": "sess-empty",
            "full_text": "Sample text for empty test.",
        }

        mock_gen_instance = MagicMock()
        mock_gen_instance.chain.invoke.return_value = "Sorry, I cannot summarize this."
        mock_generator_cls.return_value = mock_gen_instance

        with patch.object(generate_notes_task, "update_state"):
            with self.assertRaises(ValueError) as ctx:
                generate_notes_task.run("sess-empty")

        self.assertIn("Failed to extract valid notes", str(ctx.exception))

    @patch("tasks.session_store")
    @patch("llm.generator.Generator")
    def test_generate_notes_task_preserves_existing_valid_notes_on_failure(self, mock_generator_cls, mock_store):
        """If session already has valid notes, failure preserves and returns existing notes."""
        valid_existing = {
            "points": [{"bullet": "Existing Note", "explanation": "Existing Exp", "example": "", "importance": "high"}]
        }
        mock_store.get.return_value = {
            "id": "sess-existing",
            "full_text": "Sample text.",
            "notes": valid_existing,
        }

        mock_gen_instance = MagicMock()
        mock_gen_instance.chain.invoke.return_value = "Non-json output"
        mock_generator_cls.return_value = mock_gen_instance

        with patch.object(generate_notes_task, "update_state"):
            res = generate_notes_task.run("sess-existing")

        self.assertEqual(res, valid_existing)

    @patch("tasks.session_store")
    @patch("llm.generator.Generator")
    def test_generate_notes_task_successful_generation(self, mock_generator_cls, mock_store):
        """Successful LLM generation stores normalized notes in session_store and returns them."""
        session_data = {
            "id": "sess-success",
            "full_text": "Full text about photosynthesis and chlorophyll.",
        }
        mock_store.get.return_value = session_data

        mock_gen_instance = MagicMock()
        mock_gen_instance.chain.invoke.return_value = '{"points": [{"bullet": "Chlorophyll", "explanation": "Green pigment absorbing light.", "example": "Leaves", "importance": "high"}]}'
        mock_generator_cls.return_value = mock_gen_instance

        with patch.object(generate_notes_task, "update_state"):
            res = generate_notes_task.run("sess-success")

        self.assertEqual(len(res["points"]), 1)
        self.assertEqual(res["points"][0]["bullet"], "Chlorophyll")
        self.assertEqual(mock_store.__setitem__.call_count, 1)


if __name__ == "__main__":
    unittest.main()
