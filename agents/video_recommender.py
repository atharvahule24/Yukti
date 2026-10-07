import re
from urllib.parse import quote
from llm.generator import Generator
from utils.json_helper import extract_json

RECOMMENDATION_PROMPT = """You are an educational recommendation assistant.
A student was asked a study question, received grading feedback, and a study tip highlighting their learning gap.
Generate a targeted learning resource topic and YouTube search query directly addressing this specific learning gap.

Question: {question}
Concept: {concept}
Feedback: {feedback}
Study Tip: {study_tip}

Rules:
1. The topic must be concise (3-6 words) and directly grounded in the current question, feedback, and study tip.
2. The search query must contain important terms from the current question and identified missing concepts.
3. Never introduce an unrelated topic.
4. Do not include markdown or text outside JSON.
5. Return ONLY valid JSON:
{{
  "topic": "Specific Topic Name",
  "query": "Targeted search query"
}}"""


def generate_grounded_recommendation(
    concept: str,
    question: str | None = None,
    feedback: str | None = None,
    study_tip: str | None = None,
    difficulty: str = "medium",
    action: str = "review",
    misconception: str | None = None,
) -> tuple[str, str]:
    """Generate grounded topic and search query addressing the student's specific learning gap."""

    # 1. If question, feedback, or study_tip is provided, try LLM generation first
    if question or feedback or study_tip:
        try:
            generator = Generator(json_mode=True)
            prompt = RECOMMENDATION_PROMPT.format(
                question=question or "N/A",
                concept=concept or "N/A",
                feedback=feedback or "N/A",
                study_tip=study_tip or "N/A",
            )
            raw = generator.chain.invoke({"context": "", "question": prompt})
            parsed = extract_json(raw)
            if parsed and isinstance(parsed, dict):
                topic = parsed.get("topic")
                query = parsed.get("query")
                if topic and query:
                    return str(topic).strip(), str(query).strip()
        except Exception:
            # Fall back to deterministic extraction if LLM is unavailable
            pass

        # 2. Deterministic grounded fallback from study_tip / question / concept
        concept_clean = (concept or "").replace("-", " ").strip().title()
        topic = concept_clean or "Concept Review"

        if study_tip:
            cleaned_tip = study_tip.strip()
            cleaned_tip = re.sub(
                r"^(review|focus on|study|understand|practice)\s+(how|that|the|why)?\s*",
                "",
                cleaned_tip,
                flags=re.IGNORECASE,
            ).rstrip(".!?;:")
            words = cleaned_tip.split()
            if 1 <= len(words) <= 6:
                topic = cleaned_tip.title()
            elif words:
                short_phrase = " ".join(words[:5]).rstrip(",;:-")
                if concept_clean and concept_clean.lower() not in short_phrase.lower():
                    topic = f"{concept_clean}: {short_phrase}".title()
                else:
                    topic = short_phrase.title()

        stop_words = {
            "in", "what", "ways", "did", "the", "of", "and", "a", "an", "to",
            "for", "from", "how", "why", "is", "are", "on", "with", "as", "by",
            "its", "it", "at", "review", "focus", "study", "your", "you"
        }
        keywords = []
        if concept:
            keywords.extend(concept.replace("-", " ").split())
        source_text = f"{study_tip or ''} {question or ''}"
        for w in re.findall(r"[A-Za-z0-9]+", source_text):
            if w.lower() not in stop_words and len(w) > 2 and w.lower() not in [k.lower() for k in keywords]:
                keywords.append(w)

        keywords.append("explanation")
        query = " ".join(keywords[:10])
        return topic, query

    # 3. Default fallback to template query if no gap context is available
    query = build_video_search_query(
        concept=concept,
        difficulty=difficulty,
        action=action,
        misconception=misconception,
    )
    return (concept or "Concept Review").replace("-", " ").strip().title(), query


def build_video_search_query(
    concept: str,
    difficulty: str = "medium",
    action: str = "review",
    misconception: str | None = None,
) -> str:
    """Build a learner-state-aware YouTube search query."""

    concept_text = (concept or "").replace("-", " ").strip()

    difficulty_terms = {
        "easy": "beginner friendly simple explanation",
        "medium": "clear detailed explanation",
        "hard": "advanced detailed explanation",
    }

    action_terms = {
        "targeted_misconception_review": "common misconceptions explained",
        "step_by_step_review": "step by step explanation",
        "example_based_review": "examples explained",
        "prerequisite_review": "basics explained",
        "review": "revision explained",
        "practice": "practice and explanation",
        "confidence_reinforcement": "quick concept review",
        "advance": "deeper explanation",
    }

    difficulty_text = difficulty_terms.get(
        difficulty,
        difficulty_terms["medium"],
    )

    action_text = action_terms.get(
        action,
        "concept explanation",
    )

    misconception_text = ""
    if misconception and misconception != "incomplete_understanding":
        misconception_text = (
            f" {misconception.replace('-', ' ')}"
        )

    return (
        f"{concept_text}{misconception_text} "
        f"{action_text} {difficulty_text}"
    )


def build_youtube_search_url(query: str) -> str:
    encoded_query = quote(query)
    return (
        "https://www.youtube.com/results"
        f"?search_query={encoded_query}"
    )


def recommend_video_search(
    concept: str,
    difficulty: str = "medium",
    action: str = "review",
    misconception: str | None = None,
    question: str | None = None,
    feedback: str | None = None,
    study_tip: str | None = None,
) -> dict:
    topic, query = generate_grounded_recommendation(
        concept=concept,
        question=question,
        feedback=feedback,
        study_tip=study_tip,
        difficulty=difficulty,
        action=action,
        misconception=misconception,
    )

    return {
        "type": "youtube_search",
        "query": query,
        "url": build_youtube_search_url(query),
        "concept": topic,
        "topic": topic,
        "base_concept": concept,
        "difficulty": difficulty,
        "action": action,
    }