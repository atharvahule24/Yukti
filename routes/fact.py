from flask import Blueprint, jsonify
from routes.store import session_store
from llm.generator import Generator

fact_bp = Blueprint('fact', __name__)

@fact_bp.route('/fact/<session_id>', methods=['GET'])
def get_fact(session_id):
    if session_id not in session_store:
        return jsonify({"fact": "Did you know that spaced repetition can dramatically improve long-term memory retention?"})
        
    full_text = session_store[session_id].get("full_text", "")
    if not full_text:
        return jsonify({"fact": "Yukti breaks down complex topics so they're easier to understand!"})
        
    try:
        generator = Generator()
        prompt = "Provide exactly ONE very short, fascinating, obscure fact from this text to keep a student entertained while they wait. Do not include introductory text, just the fact."
        res = generator.chain.invoke({"context": full_text[:5000], "question": prompt})
        fact = str(res).strip()
        if fact.startswith('"') and fact.endswith('"'):
            fact = fact[1:-1]
        return jsonify({"fact": fact})
    except Exception as e:
        return jsonify({"fact": "Active recall is one of the most effective study methods!"})
