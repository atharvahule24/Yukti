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
        """Celery task generate_graph_task returns existing valid cached graph without regenerating."""
        cached_graph = {
            "nodes": [
                {"id": "cached_node_1", "label": "Cached 1", "subject": "Test"},
                {"id": "cached_node_2", "label": "Cached 2", "subject": "Test"}
            ],
            "links": [{"source": "cached_node_1", "target": "cached_node_2", "label": "includes"}]
        }
        self.memory_store[self.session_id]["graph"] = cached_graph

        with patch("tasks.session_store", self.memory_store), \
             patch.object(generate_graph_task, "update_state"), \
             patch("processing.graph_extractor.extract_knowledge_graph") as mock_extractor:
            result = generate_graph_task.run(self.session_id)

            # extract_knowledge_graph should NOT be called because graph was already cached
            mock_extractor.assert_not_called()
            self.assertEqual(result, cached_graph)

    def test_generate_graph_task_regenerates_degenerate_cached_graph(self):
        """When cached graph is degenerate (e.g. only 1 node and 0 edges), generate_graph_task re-extracts."""
        degenerate_graph = {
            "nodes": [{"id": "single_node", "label": "Single Root Node", "subject": "Test"}],
            "edges": [],
            "links": []
        }
        self.memory_store[self.session_id]["graph"] = degenerate_graph

        fresh_graph = {
            "nodes": [
                {"id": "root", "label": "Root", "subject": "Test"},
                {"id": "branch", "label": "Branch", "subject": "Test"}
            ],
            "edges": [{"source": "root", "target": "branch", "label": "includes"}],
            "links": [{"source": "root", "target": "branch", "label": "includes"}]
        }

        with patch("tasks.session_store", self.memory_store), \
             patch.object(generate_graph_task, "update_state"), \
             patch("processing.graph_extractor.extract_knowledge_graph", return_value=fresh_graph) as mock_extractor:
            result = generate_graph_task.run(self.session_id)

            mock_extractor.assert_called_once()
            self.assertEqual(result, fresh_graph)
            self.assertEqual(self.memory_store[self.session_id]["graph"], fresh_graph)

    def test_generate_graph_task_force_regeneration(self):
        """When force=True, generate_graph_task re-extracts even if a valid cached graph exists."""
        cached_graph = {
            "nodes": [
                {"id": "c1", "label": "C1", "subject": "Bio"},
                {"id": "c2", "label": "C2", "subject": "Bio"}
            ],
            "links": [{"source": "c1", "target": "c2", "label": "includes"}]
        }
        self.memory_store[self.session_id]["graph"] = cached_graph

        new_graph = {
            "nodes": [
                {"id": "new1", "label": "New 1", "subject": "Bio"},
                {"id": "new2", "label": "New 2", "subject": "Bio"}
            ],
            "links": [{"source": "new1", "target": "new2", "label": "includes"}]
        }

        with patch("tasks.session_store", self.memory_store), \
             patch.object(generate_graph_task, "update_state"), \
             patch("processing.graph_extractor.extract_knowledge_graph", return_value=new_graph) as mock_extractor:
            result = generate_graph_task.run(self.session_id, force=True)

            mock_extractor.assert_called_once()
            self.assertEqual(result, new_graph)

    def test_generate_graph_task_force_preserves_valid_graph_on_failed_extraction(self):
        """When force=True but extraction returns empty or fails, existing valid graph is preserved."""
        cached_graph = {
            "nodes": [
                {"id": "valid1", "label": "Valid 1", "subject": "Bio"},
                {"id": "valid2", "label": "Valid 2", "subject": "Bio"}
            ],
            "links": [{"source": "valid1", "target": "valid2", "label": "includes"}]
        }
        self.memory_store[self.session_id]["graph"] = cached_graph

        failed_graph = {"nodes": [], "edges": [], "links": []}

        with patch("tasks.session_store", self.memory_store), \
             patch.object(generate_graph_task, "update_state"), \
             patch("processing.graph_extractor.extract_knowledge_graph", return_value=failed_graph) as mock_extractor:
            result = generate_graph_task.run(self.session_id, force=True)

            mock_extractor.assert_called_once()
            # Must preserve the cached valid graph rather than overwriting with empty
            self.assertEqual(result, cached_graph)
            self.assertEqual(self.memory_store[self.session_id]["graph"], cached_graph)

    def test_generate_graph_task_exception_preserves_valid_graph(self):
        """When regeneration raises an unhandled exception, existing valid graph remains preserved."""
        cached_graph = {
            "nodes": [
                {"id": "c1", "label": "Concept 1", "subject": "Bio"},
                {"id": "c2", "label": "Concept 2", "subject": "Bio"}
            ],
            "links": [{"source": "c1", "target": "c2", "label": "includes"}]
        }
        self.memory_store[self.session_id]["graph"] = cached_graph

        with patch("tasks.session_store", self.memory_store), \
             patch.object(generate_graph_task, "update_state"), \
             patch("processing.graph_extractor.extract_knowledge_graph", side_effect=RuntimeError("Groq service failure")):
            with self.assertRaises(RuntimeError):
                generate_graph_task.run(self.session_id, force=True)

            # Valid cached graph in session_store was not destroyed
            self.assertEqual(self.memory_store[self.session_id]["graph"], cached_graph)

    def test_generate_graph_task_preserves_isolated_concepts_as_valid(self):
        """A graph containing 2+ nodes without edges is valid (isolated concepts) and not re-extracted unless force=True."""
        isolated_graph = {
            "nodes": [
                {"id": "iso1", "label": "Iso 1", "subject": "Bio"},
                {"id": "iso2", "label": "Iso 2", "subject": "Bio"}
            ],
            "links": [],
            "edges": []
        }
        self.memory_store[self.session_id]["graph"] = isolated_graph

        with patch("tasks.session_store", self.memory_store), \
             patch.object(generate_graph_task, "update_state"), \
             patch("processing.graph_extractor.extract_knowledge_graph") as mock_extractor:
            result = generate_graph_task.run(self.session_id, force=False)

            # extract_knowledge_graph should NOT be called because 2+ isolated nodes are a valid graph
            mock_extractor.assert_not_called()
            self.assertEqual(result, isolated_graph)

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


class TestGraphRoutes(unittest.TestCase):
    def setUp(self):
        from flask import Flask
        from routes.graph import graph_bp

        self.app = Flask(__name__)
        self.app.register_blueprint(graph_bp, url_prefix="/api")
        self.client = self.app.test_client()
        self.session_id = "test-graph-route-session-123"
        self.memory_store = {
            self.session_id: {
                "id": self.session_id,
                "title": "Route Session",
                "full_text": "Sample text for route test"
            }
        }

    def test_get_graph_returns_empty_for_degenerate_single_node_graph(self):
        """GET /api/graph returns empty nodes/links if graph only has 1 node and 0 links."""
        degenerate_graph = {
            "nodes": [{"id": "single", "label": "Single", "subject": "Bio"}],
            "edges": [],
            "links": []
        }
        self.memory_store[self.session_id]["graph"] = degenerate_graph

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.graph.session_store", self.memory_store):
            resp = self.client.get(
                f"/api/graph/{self.session_id}",
                headers={"Authorization": "Bearer mock-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["nodes"], [])
            self.assertEqual(data["links"], [])

    def test_get_graph_returns_valid_multinode_graph(self):
        """GET /api/graph returns the full graph when it has multiple connected nodes."""
        valid_graph = {
            "nodes": [
                {"id": "a", "label": "A", "subject": "Bio"},
                {"id": "b", "label": "B", "subject": "Bio"}
            ],
            "links": [{"source": "a", "target": "b", "label": "includes"}]
        }
        self.memory_store[self.session_id]["graph"] = valid_graph

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.graph.session_store", self.memory_store):
            resp = self.client.get(
                f"/api/graph/{self.session_id}",
                headers={"Authorization": "Bearer mock-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(len(data["nodes"]), 2)
            self.assertEqual(len(data["links"]), 1)

    def test_get_graph_returns_isolated_concepts_when_valid(self):
        """GET /api/graph returns graph when 2+ isolated concepts exist without edges."""
        isolated_graph = {
            "nodes": [
                {"id": "c1", "label": "Concept 1", "subject": "Bio"},
                {"id": "c2", "label": "Concept 2", "subject": "Bio"}
            ],
            "links": []
        }
        self.memory_store[self.session_id]["graph"] = isolated_graph

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.graph.session_store", self.memory_store):
            resp = self.client.get(
                f"/api/graph/{self.session_id}",
                headers={"Authorization": "Bearer mock-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(len(data["nodes"]), 2)
            self.assertEqual(len(data["links"]), 0)

    def test_generate_graph_forwards_force_flag(self):
        """POST /api/graph/generate forwards force parameter to celery task delay."""
        mock_task = MagicMock()
        mock_task.id = "mock-task-id-456"

        with patch("utils.auth.get_user_id_by_token", return_value=1), \
             patch("utils.auth.verify_session_owner", return_value=(True, 200)), \
             patch("routes.graph.session_store", self.memory_store), \
             patch("tasks.generate_graph_task.delay", return_value=mock_task) as mock_delay:
            resp = self.client.post(
                f"/api/graph/generate/{self.session_id}",
                json={"force": True},
                headers={"Authorization": "Bearer mock-token"}
            )
            self.assertEqual(resp.status_code, 202)
            mock_delay.assert_called_once_with(self.session_id, force=True)


class TestGraphTraversalAlgorithm(unittest.TestCase):
    """Verifies that the traversal model handles cyclic graphs, disconnected components, and isolated nodes."""

    def endpoint_id(self, ep):
        if ep is None:
            return ""
        if isinstance(ep, dict):
            return str(ep.get("id", ""))
        return str(ep)

    def simulate_traversal(self, nodes_data, links_data, expanded_ids=None):
        if not nodes_data:
            return {"nodes": [], "links": []}

        styled_nodes = [{**n} for n in nodes_data]
        node_map = {n["id"]: n for n in styled_nodes}
        graph_links = links_data

        incoming_count = {n["id"]: 0 for n in styled_nodes}
        for l in graph_links:
            target_id = self.endpoint_id(l.get("target"))
            incoming_count[target_id] = incoming_count.get(target_id, 0) + 1

        roots = [n for n in styled_nodes if incoming_count.get(n["id"], 0) == 0]
        if not roots and styled_nodes:
            roots = [styled_nodes[0]]

        # Ensure every disconnected component has a root
        reached_from_roots = set(r["id"] for r in roots)
        reach_queue = list(reached_from_roots)
        while reach_queue:
            curr_id = reach_queue.pop(0)
            for l in graph_links:
                s = self.endpoint_id(l.get("source"))
                t = self.endpoint_id(l.get("target"))
                if s == curr_id and t not in reached_from_roots:
                    reached_from_roots.add(t)
                    reach_queue.append(t)
                elif t == curr_id and s not in reached_from_roots:
                    reached_from_roots.add(s)
                    reach_queue.append(s)

        for n in styled_nodes:
            if n["id"] not in reached_from_roots:
                roots.append(n)
                reached_from_roots.add(n["id"])
                reach_queue.append(n["id"])
                while reach_queue:
                    curr_id = reach_queue.pop(0)
                    for l in graph_links:
                        s = self.endpoint_id(l.get("source"))
                        t = self.endpoint_id(l.get("target"))
                        if s == curr_id and t not in reached_from_roots:
                            reached_from_roots.add(t)
                            reach_queue.append(t)
                        elif t == curr_id and s not in reached_from_roots:
                            reached_from_roots.add(s)
                            reach_queue.append(s)

        expanded_nodes = set(n["id"] for n in styled_nodes) if expanded_ids is None else set(expanded_ids)
        visible_nodes = set()

        queue = []
        enqueued = set()
        for r in roots:
            queue.append(r)
            enqueued.add(r["id"])

        while queue:
            node = queue.pop(0)
            visible_nodes.add(node["id"])

            if node["id"] in expanded_nodes:
                neighbor_links = [
                    l for l in graph_links
                    if self.endpoint_id(l.get("source")) == node["id"] or self.endpoint_id(l.get("target")) == node["id"]
                ]
                for l in neighbor_links:
                    neighbor_id = (
                        self.endpoint_id(l.get("target"))
                        if self.endpoint_id(l.get("source")) == node["id"]
                        else self.endpoint_id(l.get("source"))
                    )
                    if neighbor_id not in enqueued:
                        neighbor_node = node_map.get(neighbor_id)
                        if neighbor_node:
                            enqueued.add(neighbor_id)
                            queue.append(neighbor_node)

        for n in styled_nodes:
            if n["id"] in expanded_nodes:
                visible_nodes.add(n["id"])

        return {
            "nodes": [n for n in styled_nodes if n["id"] in visible_nodes],
            "links": [
                l for l in graph_links
                if self.endpoint_id(l.get("source")) in visible_nodes and self.endpoint_id(l.get("target")) in visible_nodes
            ]
        }

    def test_cyclic_graph_traversal_terminates_safely(self):
        """Cyclic graphs (A -> B -> C -> A) terminate cleanly with all nodes visible."""
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        links = [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
            {"source": "c", "target": "a"},
        ]
        res = self.simulate_traversal(nodes, links)
        self.assertEqual(len(res["nodes"]), 3)
        self.assertEqual(len(res["links"]), 3)

    def test_disconnected_components_and_isolated_nodes_reachable(self):
        """Disconnected components, isolated concepts, and cycles without 0-incoming roots are visible."""
        nodes = [
            {"id": "main_root"},
            {"id": "main_child"},
            {"id": "isolated_concept"},
            {"id": "disconn_cycle_1"},
            {"id": "disconn_cycle_2"},
        ]
        links = [
            {"source": "main_root", "target": "main_child"},
            {"source": "disconn_cycle_1", "target": "disconn_cycle_2"},
            {"source": "disconn_cycle_2", "target": "disconn_cycle_1"},
        ]
        res = self.simulate_traversal(nodes, links)
        self.assertEqual(len(res["nodes"]), 5)
        self.assertEqual(len(res["links"]), 3)


if __name__ == "__main__":
    unittest.main()
