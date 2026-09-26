import json
import os

from dotenv import load_dotenv
from groq import Groq

from agents.concept_registry import get_canonical_concepts

load_dotenv()


def detect_misconception(
    question: str,
    student_answer: str,
    sample_answer: str,
    concept: str,
) -> dict:
    """
    Analyze a student's incorrect or incomplete answer and identify
    the likely misconception behind the error.
    """

    canonical_concepts = get_canonical_concepts(concept)

    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

    prompt = f"""
You are an educational misconception detector.

Your job is NOT to simply grade the student's answer.
Your job is to identify WHY the student may have answered incorrectly
or incompletely.

Question:
{question}

Sample answer:
{sample_answer}

Student answer:
{student_answer}

Main concept:
{concept}

Canonical concepts:
{json.dumps(canonical_concepts, ensure_ascii=False)}

Analyze the student's reasoning carefully.

Rules:
- Identify a misconception only when the student's answer contains
  evidence of an incorrect belief, incorrect causal relationship,
  or incorrect explanation.

- IMPORTANT:
  Missing facts, missing examples, short answers, or failure to mention
  all expected points are NOT by themselves misconceptions.

- If the student's statements are correct but incomplete, use:
  "incomplete_understanding"

- If the student gives correct reasoning but omits supporting examples,
  specific adaptations, consequences, or details from the sample answer,
  classify it as:
  "incomplete_understanding"

- Use a specific misconception only when the student actually states
  or clearly implies something incorrect.

- Do not infer a misconception merely because information is absent.

- severity must be one of: "low", "medium", "high".
  Use:
  "low" for incomplete understanding or minor gaps,
  "medium" for a meaningful conceptual misunderstanding,
  "high" for a major or fundamental misconception.

- suggested_intervention should be one concrete teaching action.

- Keep the misconception specific and educationally useful.
- Use ONLY the provided canonical concepts.

Return ONLY valid JSON:

{{
    "concept": "canonical concept ID or concept name",
    "misconception": "specific misconception or incomplete_understanding",
    "evidence": "short explanation based on the student's answer",
    "severity": "low",
    "suggested_intervention": "one specific teaching action"
}}
"""

    response = client.chat.completions.create(
       model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise educational misconception detector. "
                    "Return only valid JSON."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.1,
    )

    content = response.choices[0].message.content

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        return {
            "concept": concept,
            "misconception": "unable_to_determine",
            "evidence": "The misconception detector returned invalid JSON.",
            "severity": "low",
            "suggested_intervention": (
                "Review the student's answer manually before adapting instruction."
            ),
        }

    return result