import os
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from processing.graph_extractor import extract_knowledge_graph
from tasks import generate_graph_task


class TestSinglePassKnowledgeGraph(unittest.TestCase):
    def setUp(self):
        self.session_id = "test-graph-session-001"
        self.sample_text = (
            "Photosynthesis is the biological process by which green plants synthesize nutrients. "
            "Photosynthesis occurs inside chloroplasts. "
            "Chlorophyll absorbs blue and red light and reflects green light. "
            "During the light-dependent reactions, ATP and NADPH are synthesized to power the Calvin cycle. "
            "Carbon dioxide is fixed into carbohydrates by the enzyme Rubisco."
        )
        self.memory_store = {
            self.session_id: {
                "id": self.session_id,
                "title": "Photosynthesis Notes",
                "full_text": self.sample_text,
                "graph": None
            }
        }

    def test_single_pass_llm_invocation_count(self):
        """Verifies that extract_knowledge_graph invokes the LLM chain exactly once (single pass)."""
        mock_raw_output = {
            "nodes": [
                {"id": "photosynthesis", "label": "Photosynthesis", "subject": "Biology"},
                {"id": "chloroplasts", "label": "Chloroplasts", "subject": "Biology"},
                {"id": "light_reactions", "label": "Light Reactions", "subject": "Biology"},
                {"id": "calvin_cycle", "label": "Calvin Cycle", "subject": "Biology"},
                {"id": "rubisco", "label": "Rubisco", "subject": "Biology"},
            ],
            "edges": [
                {"source": "photosynthesis", "target": "chloroplasts", "label": "applied_in"},
                {"source": "photosynthesis", "target": "light_reactions", "label": "includes"},
                {"source": "photosynthesis", "target": "calvin_cycle", "label": "includes"},
                {"source": "calvin_cycle", "target": "rubisco", "label": "requires"},
            ]
        }

        from langchain_core.runnables import RunnableSequence
        with patch.object(RunnableSequence, "invoke", return_value=mock_raw_output) as mock_invoke:
            with patch.dict(os.environ, {"GROQ_API_KEY": "mock_groq_key"}):
                result = extract_knowledge_graph(self.sample_text, file_path=None)

        # The chain should have been invoked exactly ONCE
        self.assertEqual(mock_invoke.call_count, 1)

        # Result must contain nodes, edges, and links
        self.assertIn("nodes", result)
        self.assertIn("edges", result)
        self.assertIn("links", result)

        self.assertEqual(len(result["nodes"]), 5)
        self.assertEqual(len(result["edges"]), 4)
        self.assertEqual(len(result["links"]), 4)

        # Verify edge referential integrity: every source and target exists in nodes
        node_ids = {n["id"] for n in result["nodes"]}
        for edge in result["edges"]:
            self.assertIn(edge["source"], node_ids)
            self.assertIn(edge["target"], node_ids)
            self.assertNotEqual(edge["source"], edge["target"])

    def test_single_pass_accepts_chunk_list_or_string(self):
        """Accepts either a string or list of Document chunks with equivalent single-pass behavior."""
        from langchain_core.documents import Document
        from langchain_core.runnables import RunnableSequence

        chunks = [
            Document(page_content="Photosynthesis occurs in chloroplasts."),
            Document(page_content="Light reactions synthesize ATP and NADPH."),
        ]

        mock_raw_output = {
            "nodes": [
                {"id": "photosynthesis", "label": "Photosynthesis", "subject": "Biology"},
                {"id": "chloroplasts", "label": "Chloroplasts", "subject": "Biology"}
            ],
            "edges": [
                {"source": "photosynthesis", "target": "chloroplasts", "label": "applied_in"}
            ]
        }

        with patch.object(RunnableSequence, "invoke", return_value=mock_raw_output) as mock_invoke:
            with patch.dict(os.environ, {"GROQ_API_KEY": "mock_groq_key"}):
                res_from_chunks = extract_knowledge_graph(chunks, file_path=None)

        self.assertEqual(mock_invoke.call_count, 1)
        self.assertEqual(len(res_from_chunks["nodes"]), 2)

    def test_generate_graph_task_uses_cached_graph(self):
        """Celery task generate_graph_task returns existing cached graph without regenerating."""
        cached_graph = {
            "nodes": [{"id": "cached_node", "label": "Cached", "subject": "Test"}],
            "links": []
        }
        self.memory_store[self.session_id]["graph"] = cached_graph

        with patch("tasks.session_store", self.memory_store), \
             patch.object(generate_graph_task, "update_state"), \
             patch("processing.graph_extractor.extract_knowledge_graph") as mock_extractor:
            result = generate_graph_task.run(self.session_id)

            # extract_knowledge_graph should NOT be called because graph was already cached
            mock_extractor.assert_not_called()
            self.assertEqual(result, cached_graph)

    def test_generate_graph_task_runs_single_pass_when_no_cache(self):
        """When no graph is cached, generate_graph_task calls single-pass extraction and stores result."""
        generated_graph = {
            "nodes": [
                {"id": "n1", "label": "N1", "subject": "Bio"},
                {"id": "n2", "label": "N2", "subject": "Bio"}
            ],
            "edges": [{"source": "n1", "target": "n2", "label": "includes"}],
            "links": [{"source": "n1", "target": "n2", "label": "includes"}]
        }

        with patch("tasks.session_store", self.memory_store), \
             patch.object(generate_graph_task, "update_state"), \
             patch("processing.graph_extractor.extract_knowledge_graph", return_value=generated_graph) as mock_extractor:
            result = generate_graph_task.run(self.session_id)

            mock_extractor.assert_called_once()
            self.assertEqual(result["nodes"], generated_graph["nodes"])
            self.assertEqual(self.memory_store[self.session_id]["graph"], result)


if __name__ == "__main__":
    unittest.main()
