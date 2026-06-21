"""
tts_manager.py — Voice synthesis for Kiana
Priority chain: Qwen3-TTS → Kokoro-ONNX → Edge TTS (cloud fallback)
"""
import os
import asyncio
import time
import threading

# Audio cache inside static so Flask can serve it directly
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'static', 'assets', 'audio')
os.makedirs(CACHE_DIR, exist_ok=True)

# ── Qwen3-TTS (primary — fully local, no API key, high quality) ──────────────
# Model : Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice  (~1.2 GB download on first run)
# Package: qwen-tts  (already installed)
# API   : Qwen3TTSModel.from_pretrained() -> .generate_custom_voice(text, speaker)

_qwen_model   = None
_qwen_loaded  = False
_qwen_loading = False
_qwen_lock    = threading.Lock()
_qwen_event   = threading.Event()   # set when load completes (success or fail)

QWEN_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
QWEN_SPEAKER  = "serena"   # warm female voice; options: serena, vivian, sohee, aiden, dylan, eric, ryan, ono_anna, uncle_fu

def _load_qwen():
    """Load Qwen3-TTS model. Thread-safe; waits if another thread is loading."""
    global _qwen_model, _qwen_loaded, _qwen_loading

    with _qwen_lock:
        if _qwen_loaded:
            return _qwen_model is not None
        if _qwen_loading:
            # Another thread owns the load — we'll wait outside the lock
            wait_for_other = True
        else:
            _qwen_loading = True
            wait_for_other = False

    if wait_for_other:
        # Wait (without holding lock) until the loader thread signals completion
        _qwen_event.wait(timeout=300)
        return _qwen_model is not None

    try:
        import torch
        from qwen_tts.inference.qwen3_tts_model import Qwen3TTSModel

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype  = torch.bfloat16 if torch.cuda.is_available() else torch.float32

        print(f"[Qwen3-TTS] Loading {QWEN_MODEL_ID} on {device}"
              f" (first run downloads ~1.2 GB)...")

        _qwen_model = Qwen3TTSModel.from_pretrained(
            QWEN_MODEL_ID,
            dtype=dtype,
            device_map="auto" if device == "cuda" else None,
        )
        print(f"[Qwen3-TTS] Ready OK (speaker: {QWEN_SPEAKER})")
        with _qwen_lock:
            _qwen_loaded = True
            _qwen_loading = False
        _qwen_event.set()
        return True

    except Exception as e:
        print(f"[Qwen3-TTS] Load failed: {e}")
        with _qwen_lock:
            _qwen_loaded = True   # mark done so we don't retry forever
            _qwen_loading = False
        _qwen_event.set()
        return False


def _preload_qwen_async():
    """Start model loading in a background thread so first request is fast."""
    t = threading.Thread(target=_load_qwen, daemon=True, name="qwen-tts-loader")
    t.start()


def synthesize_qwen3(text: str, output_file: str) -> bool:
    """
    Generate speech with Qwen3-TTS and write a WAV file.
    Returns True on success.
    """
    global _qwen_model, _qwen_loaded

    if not _qwen_loaded:
        if not _load_qwen():
            return False

    if _qwen_model is None:
        return False

    try:
        import soundfile as sf

        wav_path = output_file if output_file.endswith(".wav") \
                   else output_file.replace(".mp3", ".wav")

        # generate_custom_voice returns (List[np.ndarray], sample_rate)
        audio_arrays, sample_rate = _qwen_model.generate_custom_voice(
            text=text,
            speaker=QWEN_SPEAKER,
            language="English",
            do_sample=True,
        )

        # audio_arrays is a list; take the first element
        audio = audio_arrays[0]
        sf.write(wav_path, audio, sample_rate)
        print(f"[Qwen3-TTS] OK  {os.path.basename(wav_path)}")
        return os.path.exists(wav_path)

    except Exception as e:
        print(f"[Qwen3-TTS] Synthesis error: {e}")
        return False


# ── Kokoro ONNX (local fallback — ~82 M params, fast, no GPU) ────────────────
_kokoro        = None
_kokoro_loaded = False

def _get_kokoro():
    global _kokoro, _kokoro_loaded
    if _kokoro_loaded:
        return _kokoro
    _kokoro_loaded = True
    try:
        from kokoro_onnx import Kokoro
        from huggingface_hub import hf_hub_download

        kokoro_dir  = os.path.join(os.path.dirname(__file__), "kokoro_models")
        os.makedirs(kokoro_dir, exist_ok=True)

        model_path  = os.path.join(kokoro_dir, "kokoro-v1.0.onnx")
        voices_path = os.path.join(kokoro_dir, "voices.bin")

        import urllib.request
        # NOTE: DmlExecutionProvider (AMD DirectML) doesn't support Kokoro's ConvTranspose ops.
        # ONNX CPU runtime is still ~20x faster than Qwen3-TTS on PyTorch CPU.
        model_url  = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
        voices_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

        model_path  = os.path.join(kokoro_dir, "kokoro-v1.0.onnx")
        voices_path = os.path.join(kokoro_dir, "voices-v1.0.bin")

        if not os.path.exists(model_path):
            print("[Kokoro] Downloading model (~350 MB)...")
            urllib.request.urlretrieve(model_url, model_path)

        if not os.path.exists(voices_path):
            print("[Kokoro] Downloading voices (~50 MB)...")
            urllib.request.urlretrieve(voices_url, voices_path)

        # Use ONNX CPU — DirectML is incompatible with Kokoro's ConvTranspose ops on AMD
        os.environ.pop("ONNX_PROVIDER", None)
        _kokoro = Kokoro(model_path, voices_path)
        print("[Kokoro] Ready OK (ONNX CPU)")
    except Exception as e:
        print(f"[Kokoro] Unavailable: {e}")
        _kokoro = None
    return _kokoro


def synthesize_kokoro(text: str, output_file: str) -> bool:
    try:
        import soundfile as sf
        kokoro = _get_kokoro()
        if kokoro is None:
            return False
        samples, sample_rate = kokoro.create(
            text, voice="af_heart", speed=1.05, lang="en-us"
        )
        wav_path = output_file if output_file.endswith(".wav") \
                   else output_file.replace(".mp3", ".wav")
        sf.write(wav_path, samples, sample_rate)
        return os.path.exists(wav_path)
    except Exception as e:
        print(f"[Kokoro] Synthesis error: {e}")
        return False


# ── GPT-SoVITS (optional personal voice clone server) ────────────────────────
def synthesize_gpt_sovits(text: str, output_file: str) -> bool:
    url       = os.getenv("GPT_SOVITS_URL")
    ref_audio = os.getenv("GPT_SOVITS_REF_AUDIO")
    ref_text  = os.getenv("GPT_SOVITS_REF_TEXT")
    if not url or not ref_audio:
        return False
    try:
        import requests
        payload = {
            "text": text, "text_lang": "en",
            "ref_audio_path": ref_audio,
            "prompt_text": ref_text, "prompt_lang": "en",
        }
        res = requests.post(url, json=payload, timeout=20)
        if res.status_code == 200:
            with open(output_file, "wb") as f:
                f.write(res.content)
            return True
        print(f"[GPT-SoVITS] HTTP {res.status_code}: {res.text[:80]}")
    except Exception as e:
        print(f"[GPT-SoVITS] Error: {e}")
    return False


# ── Edge TTS (cloud, always-available last resort) ────────────────────────────
async def _edge_async(text: str, output_file: str) -> bool:
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, "en-US-AnaNeural")
        await communicate.save(output_file)
        return True
    except Exception as e:
        print(f"[Edge TTS] Error: {e}")
        return False

def synthesize_edge(text: str, output_file: str) -> bool:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(_edge_async(text, output_file))
    loop.close()
    return result


# ── Startup: preload Qwen3-TTS in background so first reply is fast ───────────
_preload_qwen_async()


# ── Main entrypoint ───────────────────────────────────────────────────────────
def generate_voice(text: str, filename: str = "response.mp3") -> str | None:
    """
    Synthesise speech for Kiana.
    Returns a relative URL to the audio file, or None on total failure.

    Priority:
      1. Kokoro ONNX — fast local fallback, ~350 MB (Instant on CPU)
      2. Qwen3-TTS   — best quality, fully local, ~1.2 GB model (Slow on CPU)
      3. GPT-SoVITS  — optional personal voice clone server
      4. Edge TTS    — cloud fallback (requires internet)
    """
    output_path = os.path.join(CACHE_DIR, filename)
    wav_path    = output_path.replace(".mp3", ".wav")

    # Purge old cached files (>5 min)
    try:
        for f in os.listdir(CACHE_DIR):
            fp = os.path.join(CACHE_DIR, f)
            if os.path.isfile(fp) and os.path.getmtime(fp) < time.time() - 300:
                os.remove(fp)
    except Exception:
        pass

    # 1. Kokoro ONNX (Extremely fast on CPU)
    if synthesize_kokoro(text, wav_path):
        return f"/static/assets/audio/{filename.replace('.mp3', '.wav')}"

    print("[TTS] Kokoro unavailable -> Qwen3-TTS...")

    # 2. Qwen3-TTS (High quality, but very slow on CPU without GPU/flash-attn)
    if synthesize_qwen3(text, wav_path):
        return f"/static/assets/audio/{filename.replace('.mp3', '.wav')}"

    print("[TTS] Kokoro unavailable -> GPT-SoVITS...")

    # 3. GPT-SoVITS
    if synthesize_gpt_sovits(text, output_path):
        return f"/static/assets/audio/{filename}"

    # 4. Edge TTS
    print("[TTS] All local backends failed -> Edge TTS (cloud)...")
    if synthesize_edge(text, output_path):
        return f"/static/assets/audio/{filename}"

    print("[TTS] All backends failed.")
    return None
