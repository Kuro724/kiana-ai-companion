"""
wake_word.py — Always-on "Hey Kiana" wake word detection.

Backend priority:
  1. faster-whisper  (best accuracy, fully local)  — requires sounddevice
  2. SpeechRecognition + Windows built-in          (no extra deps, always works)
  3. Disabled                                       (graceful fallback)
"""
import threading
import time
import os
import io

# ── Import availability flags ─────────────────────────────────────────────────
try:
    import sounddevice as sd
    import numpy as np
    HAS_SOUNDDEVICE = True
except Exception:
    HAS_SOUNDDEVICE = False

try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = HAS_SOUNDDEVICE   # only useful if sounddevice also works
except Exception:
    HAS_WHISPER = False

try:
    import speech_recognition as sr
    HAS_SR = True
except Exception:
    HAS_SR = False

# ── Config ────────────────────────────────────────────────────────────────────
WAKE_PHRASE = os.getenv("WAKE_WORD", "hey kiana").lower()
ENABLED     = os.getenv("WAKE_WORD_ENABLED", "true").lower() == "true"
SAMPLE_RATE = 16000


class WakeWordListener:
    """
    Background daemon that continuously listens for the wake phrase.
    Tries faster-whisper first, falls back to SpeechRecognition.
    """

    def __init__(self, on_wake=None, on_response=None):
        self.on_wake     = on_wake
        self.on_response = on_response
        self.running     = False
        self._model      = None
        self._recognizer = None
        self._mic        = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        if not ENABLED:
            print("Wake word disabled via WAKE_WORD_ENABLED=false.")
            return False

        if HAS_WHISPER and HAS_SOUNDDEVICE:
            print("Wake word: using faster-whisper backend.")
            self.running = True
            threading.Thread(target=self._run_whisper, daemon=True).start()
            return True

        if HAS_SR:
            print("Wake word: using SpeechRecognition (Windows speech) backend.")
            self._recognizer = sr.Recognizer()
            self._recognizer.dynamic_energy_threshold = True
            try:
                self._mic = sr.Microphone()
            except Exception as e:
                print(f"Wake word disabled: no microphone ({e}).")
                return False
            self.running = True
            threading.Thread(target=self._run_sr, daemon=True).start()
            return True

        print("Wake word disabled: no suitable audio backend available.")
        return False

    def stop(self):
        self.running = False

    # ── faster-whisper backend ────────────────────────────────────────────────

    def _load_whisper(self):
        if self._model is None:
            try:
                print("Wake word: loading Whisper tiny.en …")
                self._model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
                print("Wake word: Whisper ready.")
            except Exception as e:
                print(f"Wake word: Whisper load failed ({e}).")
                self._model = None
        return self._model

    def _record(self, seconds: float):
        frames = int(seconds * SAMPLE_RATE)
        audio  = sd.rec(frames, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
        sd.wait()
        return audio.flatten()

    def _transcribe(self, audio_np, beam_size=1) -> str:
        model = self._load_whisper()
        if model is None:
            return ""
        try:
            segs, _ = model.transcribe(audio_np, beam_size=beam_size, language="en")
            return " ".join(s.text for s in segs).lower().strip()
        except Exception as e:
            print(f"Wake word transcribe error: {e}")
            return ""

    def _run_whisper(self):
        self._load_whisper()
        print(f"Wake word (whisper): listening for '{WAKE_PHRASE}' …")
        while self.running:
            try:
                audio = self._record(2.0)
                text  = self._transcribe(audio)
                if text and WAKE_PHRASE in text:
                    print(f"  ✨ Wake word detected: '{text}'")
                    self._fire_wake()
                    self._handle_command_whisper()
            except Exception as e:
                print(f"Wake word loop error: {e}")
                time.sleep(1)

    def _handle_command_whisper(self):
        print("  🎤 Listening for command (5 s) …")
        audio   = self._record(5.0)
        command = self._transcribe(audio, beam_size=3).strip()
        if not command or len(command) < 3:
            print("  ⚠️  No clear command.")
            return
        self._send_command(command)

    # ── SpeechRecognition backend ─────────────────────────────────────────────

    def _run_sr(self):
        print(f"Wake word (SR): listening for '{WAKE_PHRASE}' …")
        with self._mic as source:
            self._recognizer.adjust_for_ambient_noise(source, duration=1)

        while self.running:
            try:
                with self._mic as source:
                    # listen() blocks until it hears audio and silence
                    audio_data = self._recognizer.listen(source, timeout=5, phrase_time_limit=4)

                try:
                    text = self._recognizer.recognize_google(audio_data).lower().strip()
                except sr.UnknownValueError:
                    text = ""
                except sr.RequestError:
                    # Offline fallback — try Windows built-in
                    try:
                        text = self._recognizer.recognize_sphinx(audio_data).lower().strip()
                    except Exception:
                        text = ""

                if text and WAKE_PHRASE in text:
                    print(f"  ✨ Wake word detected: '{text}'")
                    self._fire_wake()
                    self._handle_command_sr()

            except sr.WaitTimeoutError:
                pass   # no speech in 5 s window — keep looping
            except Exception as e:
                print(f"Wake word SR loop error: {e}")
                time.sleep(1)

    def _handle_command_sr(self):
        """Capture a follow-up command via SpeechRecognition."""
        print("  🎤 Listening for command …")
        try:
            with self._mic as source:
                audio_data = self._recognizer.listen(source, timeout=8, phrase_time_limit=6)
            try:
                command = self._recognizer.recognize_google(audio_data).strip()
            except Exception:
                command = ""
        except Exception as e:
            print(f"  SR command listen error: {e}")
            return

        if not command or len(command) < 2:
            print("  ⚠️  No clear command.")
            return
        self._send_command(command)

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _fire_wake(self):
        if self.on_wake:
            threading.Thread(target=self.on_wake, daemon=True).start()

    def _send_command(self, command: str):
        import requests as _req
        print(f"  📝 Command: '{command}'")
        try:
            base = f"http://127.0.0.1:{os.getenv('PORT', '5000')}"
            chat = _req.post(f"{base}/api/chat",
                             json={"message": command}, timeout=30).json()
            bot_response = chat.get("response", "")
            emotion      = chat.get("emotion", "Relaxed")

            tts = _req.post(f"{base}/api/voice-tts",
                            json={"text": bot_response}, timeout=30).json()
            audio_url = tts.get("audio_url", "")

            if self.on_response:
                self.on_response(command, bot_response, emotion, audio_url)
        except Exception as e:
            print(f"  ❌ Wake word command error: {e}")


# ── Singleton factory ─────────────────────────────────────────────────────────
_listener: "WakeWordListener | None" = None

def get_listener(on_wake=None, on_response=None) -> WakeWordListener:
    global _listener
    if _listener is None:
        _listener = WakeWordListener(on_wake=on_wake, on_response=on_response)
    return _listener
