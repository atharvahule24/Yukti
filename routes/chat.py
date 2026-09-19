import json
from flask import Blueprint, request, Response, stream_with_context, jsonify
from agents.rag_workflow import RagWorkflow

chat_bp = Blueprint('chat', __name__)
rag_workflow = RagWorkflow()

@chat_bp.route('/chat', methods=['GET'])
def chat():
    message = request.args.get('message', '')
    session_id = request.args.get('session_id', '')
    mode = request.args.get('mode', 'normal')

    if not message:
        return jsonify({"error": "Message is required"}), 400

    def generate():
        try:
            for event in rag_workflow.run(message, session_id, mode):
                if isinstance(event, dict) and event.get("type") == "citations":
                    yield f'event: citations\ndata: {json.dumps(event.get("data", []))}\n\n'
                else:
                    token = event.get("data", "") if isinstance(event, dict) else event
                    yield f'data: {json.dumps({"token": token, "done": False})}\n\n'
            
            yield f'data: {json.dumps({"token": "", "done": True})}\n\n'
        except Exception as e:
            yield f'data: {json.dumps({"error": str(e), "done": True})}\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*"
        }
    )
