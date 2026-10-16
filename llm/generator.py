import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

class Generator:

    def __init__(self, json_mode=False, max_tokens=None):

        groq_api_key = os.environ.get("GROQ_API_KEY")

        model_kwargs = {}
        if json_mode:
            model_kwargs["response_format"] = {"type": "json_object"}

        effective_max_tokens = max_tokens if max_tokens is not None else (1500 if json_mode else 3000)

        self.model = ChatGroq(
            model_name="openai/gpt-oss-20b",  # fallback to standard names on Groq
            temperature=0.3,
            max_tokens=effective_max_tokens,
            api_key=groq_api_key,
            model_kwargs=model_kwargs
        )

        if json_mode:
            self.prompt = PromptTemplate(
                template="""Context:
{context}

Task:
{question}
""",
                input_variables=["context", "question"]
            )
        else:
            self.prompt = PromptTemplate(
                template="""You are a helpful study assistant and an expert teacher.
First, refer strictly to the provided context. If the context contains the answer, base your response entirely on it.
If the context is insufficient or empty to answer the question, do NOT say "I don't know." Instead, use your own broad knowledge base to explain the concept. Adopt a teaching style: be encouraging, engaging, and clear, acting as an active study companion to teach the topic naturally.

Context:
{context}

Question:
{question}
""",
                input_variables=["context", "question"]
            )

        self.chain = self.prompt | self.model | StrOutputParser()

    def generate(self, docs, question):
        context = "\n\n".join(doc.page_content for doc in docs)
        return self.chain.invoke({"context": context, "question": question})
