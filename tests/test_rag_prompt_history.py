import os
import sys
from pathlib import Path
import dotenv

# Reconfigure stdout for Windows console to handle UTF-8 characters like \u2192 in prompts
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

# Load .env so db.py initializes without throwing on missing env vars
dotenv.load_dotenv(WORKSPACE_ROOT / ".env")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_key")

import unittest
from unittest.mock import patch, MagicMock
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableLambda

# Import RagWorkflow from application code
from agents.rag_workflow import RagWorkflow

class TestRagPromptHistory(unittest.TestCase):
    @patch('agents.rag_workflow.get_history')
    @patch('agents.rag_workflow.save_message')
    @patch('agents.rag_workflow.VectorStore')
    @patch('agents.rag_workflow.Embedder')
    @patch('agents.rag_workflow.ChatGroq')
    def test_historical_json_with_braces(self, mock_chat_groq, mock_embedder, mock_vector_store, mock_save_msg, mock_get_history):
        """Test that historical messages containing JSON/curly braces do not get treated as prompt template variables."""
        mock_chat_groq.return_value = RunnableLambda(lambda x: MagicMock(content="Here is the explanation."))

        mock_vs_instance = MagicMock()
        mock_vs_instance.search.return_value = []
        mock_vector_store.return_value = mock_vs_instance

        # History with JSON / dictionary braces
        mock_get_history.return_value = [
            {"role": "user", "content": "How do I format a JSON dictionary with {'name': 'Alice', 'role': 'admin'}?"},
            {"role": "assistant", "content": "You can define it in Python as: data = {'status': 'active', 'code': 200}"}
        ]

        workflow = RagWorkflow()
        events = list(workflow.run(message="Can you explain that?", session_id="test-session-json", mode="socratic"))

        tokens = [e for e in events if e.get("type") == "token"]
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0]["data"], "Here is the explanation.")

    @patch('agents.rag_workflow.get_history')
    @patch('agents.rag_workflow.save_message')
    @patch('agents.rag_workflow.VectorStore')
    @patch('agents.rag_workflow.Embedder')
    @patch('agents.rag_workflow.ChatGroq')
    def test_unmatched_opening_brace_in_code(self, mock_chat_groq, mock_embedder, mock_vector_store, mock_save_msg, mock_get_history):
        """Test that historical messages with unmatched opening curly braces do not raise ValueError."""
        mock_chat_groq.return_value = RunnableLambda(lambda x: MagicMock(content="Missing closing brace syntax explanation."))

        mock_vs_instance = MagicMock()
        mock_vs_instance.search.return_value = []
        mock_vector_store.return_value = mock_vs_instance

        # History with unmatched opening brace
        mock_get_history.return_value = [
            {"role": "user", "content": "Why is this function syntax invalid: void main() { return; "}
        ]

        workflow = RagWorkflow()
        events = list(workflow.run(message="Please explain the error", session_id="test-session-brace", mode="socratic"))

        tokens = [e for e in events if e.get("type") == "token"]
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0]["data"], "Missing closing brace syntax explanation.")

    @patch('agents.rag_workflow.get_history')
    @patch('agents.rag_workflow.save_message')
    @patch('agents.rag_workflow.VectorStore')
    @patch('agents.rag_workflow.Embedder')
    @patch('agents.rag_workflow.ChatGroq')
    def test_normal_history_and_input_variables_and_order(self, mock_chat_groq, mock_embedder, mock_vector_store, mock_save_msg, mock_get_history):
        """Test normal user and assistant history, correct message order, and exact expected input variables."""
        mock_chat_groq.return_value = RunnableLambda(lambda x: MagicMock(content="Response to question."))

        mock_vs_instance = MagicMock()
        doc_mock = MagicMock(page_content="Photosynthesis converts light energy into chemical energy.", metadata={"page": 1, "source": "biology.pdf"})
        mock_vs_instance.search.return_value = [doc_mock]
        mock_vector_store.return_value = mock_vs_instance

        mock_get_history.return_value = [
            {"role": "user", "content": "What is photosynthesis?"},
            {"role": "assistant", "content": "Photosynthesis is the process plants use to make food."},
            {"role": "system", "content": "Internal system note that should be filtered out"}
        ]

        workflow = RagWorkflow()

        system_prompt = workflow._get_system_prompt("socratic")
        rag_system_prompt = system_prompt + "\n\nRetrieved study material:\n{context}\n"

        history = mock_get_history.return_value
        history_messages = [
            HumanMessage(content=item["content"])
            if item["role"] == "user"
            else AIMessage(content=item["content"])
            for item in history
            if item["role"] in {"user", "assistant"}
        ]

        from langchain_core.prompts import ChatPromptTemplate
        prompt = ChatPromptTemplate.from_messages([
            ("system", rag_system_prompt),
            *history_messages,
            ("user", "{message}")
        ])

        # 1. Verify expected prompt input variables are STRICTLY context and message
        self.assertEqual(set(prompt.input_variables), {"context", "message"})

        # 2. Format messages and verify order
        formatted_messages = prompt.format_messages(context="Doc content", message="How does chlorophyll work?")
        self.assertEqual(len(formatted_messages), 4)

        # Message 0: SystemMessage
        self.assertIsInstance(formatted_messages[0], SystemMessage)
        self.assertIn("Doc content", formatted_messages[0].content)

        # Message 1: HumanMessage (first user history)
        self.assertIsInstance(formatted_messages[1], HumanMessage)
        self.assertEqual(formatted_messages[1].content, "What is photosynthesis?")

        # Message 2: AIMessage (first assistant history)
        self.assertIsInstance(formatted_messages[2], AIMessage)
        self.assertEqual(formatted_messages[2].content, "Photosynthesis is the process plants use to make food.")

        # Message 3: HumanMessage (current user message)
        self.assertIsInstance(formatted_messages[3], HumanMessage)
        self.assertEqual(formatted_messages[3].content, "How does chlorophyll work?")

        # 3. Verify workflow.run succeeds end-to-end
        events = list(workflow.run(message="How does chlorophyll work?", session_id="test-session-order", mode="socratic"))
        tokens = [e for e in events if e.get("type") == "token"]
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0]["data"], "Response to question.")

    @patch('agents.rag_workflow.get_history')
    @patch('agents.rag_workflow.save_message')
    @patch('agents.rag_workflow.VectorStore')
    @patch('agents.rag_workflow.Embedder')
    @patch('agents.rag_workflow.ChatGroq')
    def test_citation_validation_and_marker_normalization(self, mock_chat_groq, mock_embedder, mock_vector_store, mock_save_msg, mock_get_history):
        """Test that valid source IDs are normalized with authoritative metadata pages, and out-of-range IDs are rejected."""
        # LLM output cites valid SOURCE 1 with a hallucinated page 999, valid shorthand SOURCE 2, and invalid SOURCE 99
        llm_output = "Chlorophyll absorbs light [SOURCE 1 | PDF PAGE 999]. ATP is synthesized [SOURCE 2]. Also bogus claim [SOURCE 99]."
        mock_chat_groq.return_value = RunnableLambda(lambda x: MagicMock(content=llm_output))

        mock_vs_instance = MagicMock()
        doc1 = MagicMock(page_content="Chloroplasts contain chlorophyll pigments.", metadata={"page": 0, "source": "bio.pdf"})
        doc2 = MagicMock(page_content="ATP synthase drives ATP phosphorylation.", metadata={"page": 3, "source": "bio.pdf"})
        mock_vs_instance.search.return_value = [doc1, doc2]
        mock_vector_store.return_value = mock_vs_instance
        mock_get_history.return_value = []

        workflow = RagWorkflow()
        events = list(workflow.run(message="How does photosynthesis work?", session_id="test-citation-grounding", mode="socratic"))

        token_events = [e for e in events if e.get("type") == "token"]
        citation_events = [e for e in events if e.get("type") == "citations"]

        self.assertEqual(len(token_events), 1)
        answer = token_events[0]["data"]

        # 1. Authoritative page 1 (zero-based 0 + 1) bound to SOURCE 1, overwriting hallucinated page 999
        self.assertIn("[SOURCE 1 | PDF PAGE 1]", answer)
        self.assertNotIn("PDF PAGE 999", answer)

        # 2. Shorthand [SOURCE 2] normalized to authoritative page 4 (zero-based 3 + 1)
        self.assertIn("[SOURCE 2 | PDF PAGE 4]", answer)

        # 3. Invalid [SOURCE 99] rejected and stripped from the text
        self.assertNotIn("SOURCE 99", answer)

        # 4. Citations payload strictly contains valid sources with authoritative pages
        self.assertEqual(len(citation_events), 1)
        citations = citation_events[0]["data"]
        self.assertEqual(len(citations), 2)
        self.assertEqual(citations[0]["source_id"], 1)
        self.assertEqual(citations[0]["page"], 1)
        self.assertEqual(citations[1]["source_id"], 2)
        self.assertEqual(citations[1]["page"], 4)

    @patch('agents.rag_workflow.get_history')
    @patch('agents.rag_workflow.save_message')
    @patch('agents.rag_workflow.VectorStore')
    @patch('agents.rag_workflow.Embedder')
    @patch('agents.rag_workflow.ChatGroq')
    def test_socratic_extended_history_and_duplicate_filtering(self, mock_chat_groq, mock_embedder, mock_vector_store, mock_save_msg, mock_get_history):
        """Verifies multi-turn Socratic history retains opening question, deduplicates double-clicks, and enforces anti-looping rules."""
        invoked_prompt = None

        def mock_invoke(inputs):
            return MagicMock(content="Great! You've nailed the complementary base-pairing rule.")

        mock_chat_groq.return_value = RunnableLambda(mock_invoke)

        mock_vs_instance = MagicMock()
        mock_vs_instance.search.return_value = []
        mock_vector_store.return_value = mock_vs_instance

        # Multi-turn history mirroring the production DNA base pairing interaction
        # Including consecutive duplicate user messages (rapid double-click)
        history_sequence = [
            {"role": "user", "content": "Why do A and T pair together in DNA?"},
            {"role": "assistant", "content": "What do you know about how bases pair in DNA?"},
            {"role": "user", "content": "Adenine pairs with thymine, and guanine pairs with cytosine."},
            {"role": "assistant", "content": "What type of bonds hold adenine and thymine together in the DNA double helix?"},
            {"role": "user", "content": "Adenine and thymine are held together by two hydrogen bonds. Guanine and cytosine by three."},
            {"role": "user", "content": "Adenine and thymine are held together by two hydrogen bonds. Guanine and cytosine by three."}, # duplicate
            {"role": "assistant", "content": "Checking question: What is the specific rule that determines which bases pair with each other in DNA?"},
        ]
        mock_get_history.return_value = history_sequence

        workflow = RagWorkflow()
        events = list(workflow.run(
            message="Adenine pairs with thymine, and guanine pairs with cytosine. This is called complementary base pairing",
            session_id="sess-dna-socratic",
            mode="socratic"
        ))

        # Check get_history was called with limit=16
        mock_get_history.assert_called_with("sess-dna-socratic", limit=16)

        # Check prompt contains anti-repetition instruction
        socratic_prompt = workflow._get_system_prompt("socratic")
        self.assertIn("Never ask the student to repeat or re-answer facts", socratic_prompt)
        self.assertIn("acknowledge their correct answer directly instead of looping", socratic_prompt)

        tokens = [e for e in events if e.get("type") == "token"]
        self.assertEqual(len(tokens), 1)
        self.assertIn("nailed the complementary base-pairing rule", tokens[0]["data"])

if __name__ == '__main__':
    unittest.main()
