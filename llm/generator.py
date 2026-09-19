import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

class Generator:

    def __init__(self, json_mode=False):

        groq_api_key = os.environ.get("GROQ_API_KEY")

        model_kwargs = {}
        if json_mode:
            model_kwargs["response_format"] = {"type": "json_object"}

        self.model = ChatGroq(
            model_name="openai/gpt-oss-20b",  # fallback to standard names on Groq
            temperature=0.3,
            max_tokens=3000,
            api_key=groq_api_key,
            model_kwargs=model_kwargs
        )

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
