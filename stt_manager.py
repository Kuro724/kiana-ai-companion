import os
import sys

# Try to load faster_whisper
try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

model = None

def init_whisper():
    global model
    if not HAS_WHISPER:
        return False
    
    if model is None:
        try:
            # base.en is significantly more accurate than tiny.en
            # still runs comfortably on CPU with INT8 quantization
            model_size = "base.en"
            print(f"Loading Whisper model: {model_size}...")
            # Run on CPU with INT8 quantization for speed
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            print("Whisper model loaded successfully.")
        except Exception as e:
            print(f"Failed to load Whisper model: {e}")
            return False
    return True

def transcribe_audio(audio_path):
    """
    Transcribes audio file to text.
    Returns the transcript string.
    """
    if not HAS_WHISPER:
        return "[Error: Whisper not installed. Using browser speech API fallback.]"
        
    if not init_whisper():
        return "[Error: Failed to initialize Whisper model.]"
        
    try:
        segments, info = model.transcribe(audio_path, beam_size=5)
        text = " ".join([segment.text for segment in segments])
        return text.strip()
    except Exception as e:
        print(f"Transcription error: {e}")
        return f"[Transcription error: {e}]"
