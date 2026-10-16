import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock
from langchain_core.runnables import RunnableLambda

import dotenv

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

dotenv.load_dotenv(WORKSPACE_ROOT / ".env")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_key")

from agents.rag_workflow import (
    RagWorkflow,
    deduplicate_and_budget_chunks,
    prune_chat_history,
)

class MockDoc:
    def __init__(self, page_content, metadata=None):
        self.page_content = page_content
        self.metadata = metadata or {}


class TestRagContextOptimization(unittest.TestCase):

    def test_context_chunk_limit_and_budget(self):
        """Verify that deduplicate_and_budget_chunks enforces chunk count and character limits."""
        # 10 chunks of 600 characters each = 6000 characters total
        docs = [
            MockDoc(f"Document chunk #{i}: " + ("x" * 570), metadata={"page": i})
            for i in range(10)
        ]

        # max_chunks=4, max_total_chars=4000
        budgeted = deduplicate_and_budget_chunks(docs, max_chunks=4, max_total_chars=4000)

        # Must not exceed max_chunks
        self.assertLessEqual(len(budgeted), 4)

        # Must not exceed character budget
        total_chars = sum(len(d.page_content) for d in budgeted)
        self.assertLessEqual(total_chars, 4000)

        # Chunks are ordered by initial relevance
        self.assertEqual(budgeted[0].metadata["page"], 0)
        self.assertEqual(budgeted[1].metadata["page"], 1)

    def test_deduplication_exact_and_substring(self):
        """Verify that exact duplicates and overlapping substring chunks are filtered out."""
        text_a = "Acids taste sour and turn blue litmus paper red."
        text_a_overlap = "turn blue litmus paper red."
        text_b = "Bases are bitter in taste and turn red litmus blue."

        docs = [
            MockDoc(text_a, metadata={"page": 0}),
            MockDoc(text_a, metadata={"page": 0}),  # exact duplicate
            MockDoc(text_a_overlap, metadata={"page": 0}),  # substring redundant
            MockDoc(text_b, metadata={"page": 1}),
        ]

        budgeted = deduplicate_and_budget_chunks(docs, max_chunks=4, max_total_chars=4000)

        # Only distinct non-redundant chunks should be retained
        self.assertEqual(len(budgeted), 2)
        self.assertEqual(budgeted[0].page_content, text_a)
        self.assertEqual(budgeted[1].page_content, text_b)

    def test_chunk_integrity_no_truncation(self):
        """Verify that individual chunks are NEVER truncated mid-chunk, preserving factual evidence."""
        crucial_evidence = (
            "Introduction to chemical indicators. "
            + ("Some background text filler. " * 15)
            + "CRUCIAL EVIDENCE: Acids change the colour of blue litmus to red."
        )

        doc = MockDoc(crucial_evidence, metadata={"page": 0})
        budgeted = deduplicate_and_budget_chunks([doc], max_chunks=4, max_total_chars=4000)

        self.assertEqual(len(budgeted), 1)
        # Ensure the entire text including the crucial evidence is fully intact
        self.assertEqual(budgeted[0].page_content, crucial_evidence)
        self.assertIn("Acids change the colour of blue litmus to red.", budgeted[0].page_content)

    def test_oversized_first_chunk_preserved_intact(self):
        """Verify that if the very first chunk exceeds the budget on its own, it is not sliced."""
        huge_chunk = "Large document section " + ("a" * 4500)
        doc = MockDoc(huge_chunk, metadata={"page": 0})

        budgeted = deduplicate_and_budget_chunks([doc], max_chunks=4, max_total_chars=4000)
        self.assertEqual(len(budgeted), 1)
        # Length remains 100% intact (not sliced to 4000 chars)
        self.assertEqual(len(budgeted[0].page_content), len(huge_chunk))

    def test_citation_preservation_and_page_numbering(self):
        """Verify that source markers and PDF page numbers are correctly assigned and preserved."""
        docs = [
            MockDoc("Litmus turns red in acid.", metadata={"page": 0, "source": "chemistry.pdf"}),
            MockDoc("Turmeric turns reddish-brown in base.", metadata={"page": 4, "source": "chemistry.pdf"}),
        ]

        budgeted = deduplicate_and_budget_chunks(docs, max_chunks=4, max_total_chars=4000)
        self.assertEqual(len(budgeted), 2)

        # Emulate context assembly in RagWorkflow
        context_parts = []
        for i, doc in enumerate(budgeted, start=1):
            raw_page = doc.metadata.get("page")
            page = raw_page + 1 if isinstance(raw_page, int) and not isinstance(raw_page, bool) else "Unknown"
            context_parts.append(f"[SOURCE {i} | PDF PAGE {page}]\n{doc.page_content}")

        context = "\n\n".join(context_parts)
        # Check source header 1 has PDF Page 1 (0-indexed page 0 + 1)
        self.assertIn("[SOURCE 1 | PDF PAGE 1]", context)
        # Check source header 2 has PDF Page 5 (0-indexed page 4 + 1)
        self.assertIn("[SOURCE 2 | PDF PAGE 5]", context)

    def test_relevant_source_selection_priority(self):
        """Verify that documents are selected in order of relevance until budget is met."""
        docs = [
            MockDoc(f"Relevance rank #{i}: " + ("content " * 120), metadata={"rank": i})
            for i in range(8)
        ]

        # Each chunk is ~980 characters; with 4000 char budget, at most 4 chunks fit
        budgeted = deduplicate_and_budget_chunks(docs, max_chunks=4, max_total_chars=4000)

        # The highest-ranked chunks (0, 1, 2, 3) must be the ones selected
        selected_ranks = [d.metadata["rank"] for d in budgeted]
        self.assertEqual(selected_ranks, [0, 1, 2, 3])

    def test_prune_chat_history_anchor_and_budget(self):
        """Verify chat history pruning retains the opening user question and most recent turns within budget."""
        # 16 messages: first is opening user goal, then 15 back-and-forths
        history = [{"role": "user", "content": "How do acids and bases react with litmus paper?"}]
        for i in range(1, 16):
            role = "assistant" if i % 2 == 1 else "user"
            history.append({"role": role, "content": f"Message turn {i}: " + ("detail " * 40)})

        pruned = prune_chat_history(history, max_messages=8, max_total_chars=2500)

        # Message count within limit
        self.assertLessEqual(len(pruned), 8)

        # Character budget respected
        total_chars = sum(len(m["content"]) for m in pruned)
        self.assertLessEqual(total_chars, 2500)

        # Opening question is anchored and preserved
        self.assertEqual(pruned[0]["role"], "user")
        self.assertEqual(pruned[0]["content"], "How do acids and bases react with litmus paper?")

        # The tail contains the most recent turns
        self.assertIn("Message turn 15", pruned[-1]["content"])

    @patch('agents.rag_workflow.get_history')
    @patch('agents.rag_workflow.save_message')
    @patch('agents.rag_workflow.VectorStore')
    @patch('agents.rag_workflow.Embedder')
    @patch('agents.rag_workflow.ChatGroq')
    def test_end_to_end_rag_workflow_token_reduction(
        self, mock_chat_groq, mock_embedder, mock_vector_store, mock_save_msg, mock_get_history
    ):
        """Verify that RagWorkflow.run end-to-end optimizes context and history before invoking the LLM."""
        captured_inputs = {}

        def mock_invoke(inputs):
            captured_inputs.update(inputs)
            return MagicMock(content="Blue litmus turns red in acid [SOURCE 1 | PDF PAGE 1].")

        mock_chat_groq.return_value = RunnableLambda(mock_invoke)

        # 8 candidate chunks returned by vector store (total ~7,000 chars)
        mock_vs_instance = MagicMock()
        mock_vs_instance.search.return_value = [
            MockDoc("Acids turn blue litmus red. " + ("fact " * 80), metadata={"page": 0, "source": "jesc102.pdf"}),
            MockDoc("Acids turn blue litmus red. " + ("fact " * 80), metadata={"page": 0, "source": "jesc102.pdf"}),  # duplicate
            MockDoc("Bases turn red litmus blue. " + ("base " * 80), metadata={"page": 1, "source": "jesc102.pdf"}),
            MockDoc("Turmeric is yellow. " + ("turmeric " * 80), metadata={"page": 2, "source": "jesc102.pdf"}),
            MockDoc("Extra chapter summary info. " + ("extra " * 80), metadata={"page": 3, "source": "jesc102.pdf"}),
            MockDoc("Another section. " + ("more " * 80), metadata={"page": 4, "source": "jesc102.pdf"}),
        ]
        mock_vector_store.return_value = mock_vs_instance

        # 12 history turns
        mock_get_history.return_value = [
            {"role": "user", "content": "What is litmus?"},
            {"role": "assistant", "content": "Litmus is a natural indicator."},
        ] + [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"Turn {i} " + ("info " * 20)}
            for i in range(10)
        ]

        workflow = RagWorkflow()
        events = list(workflow.run(
            message="What happens when blue litmus paper is placed in an acidic solution?",
            session_id="sess-litmus-test",
            mode="normal"
        ))

        # Check vector search was requested with k=5 instead of k=10
        mock_vs_instance.search.assert_called_with(
            "What happens when blue litmus paper is placed in an acidic solution?",
            k=5,
            session_id="sess-litmus-test"
        )

        # Check context passed to LLM was budgeted in the formatted SystemMessage
        messages = captured_inputs.get("messages", [])
        self.assertTrue(len(messages) > 0)
        system_content = messages[0].content
        self.assertIn("[SOURCE 1 | PDF PAGE 1]", system_content)
        self.assertIn("[SOURCE 4 | PDF PAGE 4]", system_content)
        # Verify candidate 5 was pruned due to max_chunks=4
        self.assertNotIn("Another section", system_content)

        # Check token and citation events
        tokens = [e for e in events if e.get("type") == "token"]
        citations = [e for e in events if e.get("type") == "citations"]

        self.assertEqual(len(tokens), 1)
        self.assertIn("[SOURCE 1 | PDF PAGE 1]", tokens[0]["data"])

        self.assertEqual(len(citations), 1)
        cit_data = citations[0]["data"]
        self.assertEqual(len(cit_data), 1)
        self.assertEqual(cit_data[0]["source_id"], 1)
        self.assertEqual(cit_data[0]["page"], 1)
        self.assertEqual(cit_data[0]["source"], "jesc102.pdf")

if __name__ == "__main__":
    unittest.main()
