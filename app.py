import os
import sys
import uuid
import time
import base64
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS

import database
import memory_manager
import tts_manager
import stt_manager

app = Flask(__name__, static_folder='static')
CORS(app)

# Initialize database
database.init_db()

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/static/<path:path>')
def send_static(path):
    resp = send_from_directory(app.static_folder, path)
    # Prevent Edge WebView2 from caching audio files
    if path.startswith('assets/audio/'):
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
    return resp

@app.route('/api/status', methods=['GET'])
def get_status():
    """
    Returns Kiana's status, familiarity score, and a personalized greeting
    based on the time of day and familiarity.
    """
    stats = database.get_relationship_stats()
    
    # 1. Determine time-of-day greeting template
    hour = datetime.now().hour
    if 5 <= hour < 12:
        greeting_time = "Good morning! Did you sleep well?"
    elif 12 <= hour < 18:
        greeting_time = "Welcome back! I hope your afternoon is going well."
    else:
        greeting_time = "It's getting late. Make sure you get some rest tonight."
        
    # 2. Adjust greeting familiarity
    fam = stats['familiarity']
    if fam == 0:
        greeting = f"Hello! Nice to meet you. I'm Kiana. {greeting_time}"
    elif fam < 20:
        greeting = f"Welcome back. It's nice to see you again! {greeting_time}"
    elif fam < 100:
        greeting = f"Hey! I was hoping you'd stop by. {greeting_time}"
    else:
        greeting = f"I'm so glad you're here. You always make my day brighter! {greeting_time}"
        
    # 3. Determine base emotional state
    history = database.get_history(limit=5)
    last_emotion = "Relaxed"
    if history:
        for msg in reversed(history):
            if msg['sender'] == 'Kiana' and msg['emotional_state']:
                last_emotion = msg['emotional_state']
                break
                
    # 4. Time context label
    hour = datetime.now().hour
    if 5 <= hour < 12:
        time_ctx = "morning"
    elif 12 <= hour < 17:
        time_ctx = "afternoon"
    elif 17 <= hour < 21:
        time_ctx = "evening"
    else:
        time_ctx = "night"

    session_summaries = database.get_session_summaries(limit=3)

    return jsonify({
        "greeting": greeting,
        "familiarity": fam,
        "interaction_count": stats['interaction_count'],
        "current_emotion": last_emotion,
        "memories": database.get_memories(),
        "time_context": time_ctx,
        "session_summaries_count": len(session_summaries),
    })

@app.route('/api/chat', methods=['POST'])
def chat():
    """
    Handles user chat message, gets Gemini response, and updates database.
    """
    data = request.json or {}
    message = data.get('message', '').strip()
    
    if not message:
        return jsonify({"error": "Empty message"}), 400
        
    # Generate response via memory manager
    result = memory_manager.generate_kiana_response(message)
    return jsonify(result)

@app.route('/api/voice-tts', methods=['POST'])
def voice_tts():
    """
    Generates high-quality TTS audio file for text.
    """
    import re
    data = request.json or {}
    text = data.get('text', '').strip()
    
    if not text:
        return jsonify({"error": "Empty text"}), 400
    
    # Strip DeepSeek <think>...</think> chain-of-thought blocks
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    
    # Truncate very long text — Qwen3-TTS on CPU is slow; keep it under ~300 chars
    # Split at sentence boundary so it doesn't cut mid-word
    if len(text) > 350:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        truncated = ''
        for s in sentences:
            if len(truncated) + len(s) + 1 > 350:
                break
            truncated = (truncated + ' ' + s).strip()
        text = truncated or text[:350]
    
    if not text:
        return jsonify({"error": "Empty text after cleanup"}), 400
    
    # Create unique filename
    filename = f"kiana_{uuid.uuid4().hex[:8]}.mp3"
    audio_url = tts_manager.generate_voice(text, filename)
    
    if audio_url:
        return jsonify({"audio_url": audio_url})
    else:
        return jsonify({"error": "Failed to generate speech"}), 500

@app.route('/api/voice-stt', methods=['POST'])
def voice_stt():
    """
    Receives recorded voice input and transcribes it to text.
    """
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
        
    audio_file = request.files['audio']
    temp_filename = f"temp_{uuid.uuid4().hex[:8]}.wav"
    temp_path = os.path.join(os.path.dirname(__file__), temp_filename)
    
    try:
        audio_file.save(temp_path)
        # Transcribe audio file using Whisper
        transcript = stt_manager.transcribe_audio(temp_path)
        return jsonify({"text": transcript})
    except Exception as e:
        print(f"STT API error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.route('/api/history', methods=['GET'])
def get_history_api():
    """
    Returns latest conversation history.
    """
    limit = request.args.get('limit', 20, type=int)
    history = database.get_history(limit=limit)
    return jsonify(history)

@app.route('/api/reset', methods=['POST'])
def reset_session():
    """
    Resets memories and chat history.
    """
    try:
        db_path = database.DB_PATH
        if os.path.exists(db_path):
            os.remove(db_path)
        database.init_db()
        return jsonify({"status": "success", "message": "Companion profile and history reset."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/screenshot', methods=['POST'])
def analyze_screenshot():
    """
    Accepts a base64-encoded PNG screenshot and returns Kiana's observation.
    Used by the mascot's 'Share Screen with Kiana' feature.
    """
    data = request.json or {}
    image_b64 = data.get('image_b64', '')
    if not image_b64:
        return jsonify({"error": "No image_b64 provided"}), 400
    result = memory_manager.analyze_screenshot(image_b64)
    return jsonify(result)


@app.route('/api/upload-vrm', methods=['POST'])
def upload_vrm():
    """
    Receives an uploaded 3D .vrm model file and saves it locally.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
        
    file = request.files['file']
    if not file.filename.endswith('.vrm'):
        return jsonify({"error": "File must have a .vrm extension"}), 400
        
    try:
        assets_dir = os.path.join(app.static_folder, 'assets')
        os.makedirs(assets_dir, exist_ok=True)
        vrm_path = os.path.join(assets_dir, 'kiana.vrm')
        file.save(vrm_path)
        return jsonify({"status": "success", "message": "3D VRM model uploaded successfully!"})
    except Exception as e:
        print(f"VRM Upload Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    host = os.getenv("HOST", "127.0.0.1")
    # threaded=True: TTS synthesis won't block chat/STT requests
    # use_reloader=False: prevents double-loading the 1.8 GB Qwen3-TTS model
    app.run(host=host, port=port, debug=True, threaded=True, use_reloader=False)
