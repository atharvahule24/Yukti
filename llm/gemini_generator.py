import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()


class GeminiError(Exception):
    """Base exception for Gemini API errors."""
    def __init__(self, message, status_code=None, raw_response=None):
        super().__init__(message)
        self.status_code = status_code
        self.raw_response = raw_response


class GeminiRateLimitError(GeminiError):
    """Exception for Gemini HTTP 429 and RESOURCE_EXHAUSTED errors."""
    def __init__(self, message="Gemini rate limit or quota exceeded (HTTP 429).", status_code=429, raw_response=None):
        super().__init__(message, status_code=status_code, raw_response=raw_response)


class GeminiGenerator:
    """
    Dedicated generator for quiz generation and grading using Google Gemini.
    Uses QUIZ_GEMINI_API_KEY and a supported free-tier Gemini model (gemini-3.5-flash-lite).
    Provides a compatible .chain.invoke(...) interface matching LangChain's contract.
    """
    def __init__(self, json_mode=False, max_tokens=None, model_name=None, api_key=None):
        self.json_mode = json_mode
        self.api_key = api_key or os.environ.get("QUIZ_GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        self.model_name = model_name or os.environ.get("QUIZ_GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.effective_max_tokens = max_tokens if max_tokens is not None else (2048 if json_mode else 3000)

        # Expose .chain so caller can do generator.chain.invoke(...)
        self.chain = self

    def __repr__(self):
        masked_key = f"{self.api_key[:4]}...{self.api_key[-4:]}" if self.api_key and len(self.api_key) > 8 else "***"
        return f"<GeminiGenerator model='{self.model_name}' api_key='{masked_key}'>"

    def invoke(self, inputs: dict) -> str:
        """
        Executes generation against Google Gemini REST API.
        inputs: dict with keys 'context' and 'question'
        """
        if not self.api_key:
            raise ValueError(
                "QUIZ_GEMINI_API_KEY is not configured. "
                "Please set QUIZ_GEMINI_API_KEY in your environment to enable Gemini quiz generation."
            )

        context = inputs.get("context", "")
        question = inputs.get("question", "")

        if self.json_mode:
            prompt_text = f"Context:\n{context}\n\nTask:\n{question}"
        else:
            prompt_text = (
                "You are a helpful study assistant and an expert teacher.\n"
                "First, refer strictly to the provided context. If the context contains the answer, base your response entirely on it.\n"
                "If the context is insufficient or empty to answer the question, do NOT say \"I don't know.\" "
                "Instead, use your own broad knowledge base to explain the concept. "
                "Adopt a teaching style: be encouraging, engaging, and clear, acting as an active study companion to teach the topic naturally.\n\n"
                f"Context:\n{context}\n\n"
                f"Question:\n{question}"
            )

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        generation_config = {
            "temperature": 0.3,
            "maxOutputTokens": self.effective_max_tokens,
        }
        if self.json_mode:
            generation_config["responseMimeType"] = "application/json"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt_text}
                    ]
                }
            ],
            "generationConfig": generation_config
        }

        # Use 10s connection timeout and 45s read timeout
        req_timeout = (10, 45)

        try:
            try:
                response = requests.post(endpoint, headers=headers, json=payload, timeout=req_timeout)
            except requests.exceptions.SSLError:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                response = requests.post(endpoint, headers=headers, json=payload, timeout=req_timeout, verify=False)

        except requests.exceptions.RequestException as req_err:
            raise RuntimeError(f"Gemini connection failed: {req_err}") from req_err

        if response.status_code == 429:
            err_json = {}
            try:
                err_json = response.json()
            except Exception:
                pass
            err_msg = err_json.get("error", {}).get("message", "Gemini rate limit or quota exceeded (HTTP 429).")
            raise GeminiRateLimitError(
                f"Gemini rate limit exceeded: {err_msg}",
                status_code=429,
                raw_response=err_json
            )

        if response.status_code != 200:
            err_json = {}
            try:
                err_json = response.json()
            except Exception:
                pass
            err_status = str(err_json.get("error", {}).get("status", "")).upper()
            err_msg = str(err_json.get("error", {}).get("message", response.text))
            
            # Detect 403 quota exhaustion
            if response.status_code == 403 and (
                "RESOURCE_EXHAUSTED" in err_status
                or "QUOTA" in err_msg.upper()
                or "EXHAUSTED" in err_msg.upper()
            ):
                raise GeminiRateLimitError(
                    f"Gemini quota exhausted: {err_msg}",
                    status_code=429,
                    raw_response=err_json
                )
            raise GeminiError(
                f"Gemini API error (HTTP {response.status_code}): {err_msg}",
                status_code=response.status_code,
                raw_response=err_json
            )

        try:
            data = response.json()
        except Exception as json_err:
            raise RuntimeError(f"Failed to parse Gemini response JSON: {json_err}") from json_err

        candidates = data.get("candidates", [])
        if not candidates:
            prompt_feedback = data.get("promptFeedback", {})
            block_reason = prompt_feedback.get("blockReason")
            if block_reason:
                raise RuntimeError(f"Gemini response blocked: {block_reason}")
            raise RuntimeError("Gemini returned no candidates in response.")

        first_candidate = candidates[0]
        finish_reason = first_candidate.get("finishReason")
        if finish_reason and finish_reason in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"):
            raise RuntimeError(f"Gemini generation blocked by safety policy: {finish_reason}")

        content = first_candidate.get("content", {})
        parts = content.get("parts", [])
        if not parts:
            raise RuntimeError("Gemini response candidate contains no content parts.")

        text_content = parts[0].get("text", "")
        return text_content.strip()

    def generate(self, docs, question: str) -> str:
        """Helper matching the original Generator.generate(docs, question) interface."""
        context = "\n\n".join(getattr(doc, "page_content", str(doc)) for doc in docs)
        return self.invoke({"context": context, "question": question})


# Alias for explicit imports
QuizGenerator = GeminiGenerator
