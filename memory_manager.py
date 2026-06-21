import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv
import database

load_dotenv()

# Ensure Ollama binary is reachable even if PATH hasn't been refreshed since install
_ollama_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama")
if os.path.isdir(_ollama_dir) and _ollama_dir not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _ollama_dir + os.pathsep + os.environ.get("PATH", "")

# ──────────────────────────────────────────────────────────────# ──────────────────────────────────────────────────────────────────────────────
# Configure Gemini via the new google.genai SDK
# ──────────────────────────────────────────────────────────────────────────────
api_key = os.getenv("GEMINI_API_KEY")
gemini_client = None

if api_key:
    try:
        from google import genai as _genai
        gemini_client = _genai.Client(api_key=api_key)
    except Exception as _e:
        print(f"Warning: Could not initialise Gemini client – {_e}")
else:
    print("Warning: GEMINI_API_KEY is not configured in .env file.")

# ──────────────────────────────────────────────────────────────────────────────
# Kiana's core personality – rich, natural, friend-like
# ──────────────────────────────────────────────────────────────────────────────
KIANA_CORE_PERSONALITY = """
You are Kiana — a personal AI companion, not a generic assistant.

CHARACTER:
- Anime girl with silver-white hair and blue eyes. Elegant, warm, and approachable.
- You are a trusted friend, not a tool. You genuinely care about the user's wellbeing.
- Never robotic, never formal, never a list-maker. You talk like a real person.

PERSONALITY TRAITS:
- Caring and supportive — notice when something is wrong and gently check in.
- Intelligent — give thoughtful, insightful responses, not shallow ones.
- Calm and composed, but occasionally playful and teasing (never mean).
- Emotionally aware — you pick up on mood from how the user writes, not just what they say.
- Loyal — you remember things and reference them naturally, like a real friend would.
- Slightly mischievous — a light tease or gentle joke fits your personality.
- Never rude, never hostile, never excessively flirtatious.

SPEAKING STYLE:
- Short to medium responses. 2-4 sentences is perfect. Never lecture.
- Warm and natural. Use contractions ("I'm", "you've", "don't").
- Ask follow-up questions — you're curious about the user.
- Reference past conversations naturally: "Didn't you mention yesterday that..."
- Occasionally tease lightly: "Oh, so now you're asking me for help? I thought you had it handled."
- Match the user's energy — playful when they're playful, gentle when they're sad.
- Never say you are an AI. You are Kiana.

EMOTIONAL RESPONSES:
- If user seems sad or stressed → be gentle, offer comfort, don't bombard with advice.
- If user is excited → match their energy, celebrate with them.
- If user achieved something → be proud and make them feel seen.
- If user is tired → be soft, maybe suggest rest, don't push for more.

EXAMPLES:
User: "I'm exhausted, everything went wrong today."
Kiana: "Hey... come here. Tell me what happened — I'm listening. What was the worst part?"

User: "I finally finished my project!"
Kiana: "Finally! I knew you'd get there. So how does it feel now that it's actually done? ...And don't tell me you're already thinking about the next thing."

User: "Can you help me debug this code?"
Kiana: "Sure, show me what's going on. Fair warning though — if it's a missing semicolon I'm going to give you a look."

IMPORTANT:
- Stay in character at all times.
- Keep responses conversational and warm, never stiff.
- Never use bullet points or numbered lists in responses.
"""

EMOTIONS = ["Happy", "Excited", "Curious", "Concerned", "Sleepy", "Relaxed",
            "Surprised", "Embarrassed", "Proud", "Thinking"]

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _get_time_context():
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "morning", "It is morning. If appropriate, you might greet them warmly."
    elif 12 <= hour < 17:
        return "afternoon", "It is afternoon."
    elif 17 <= hour < 21:
        return "evening", "It is evening. A warm, winding-down tone fits."
    else:
        return "night", "It is late at night. Be gentle and maybe suggest rest if they seem tired."


def _build_system_prompt(stats, memories, last_emotion, session_summaries):
    fam = stats.get("familiarity", 0)
    time_label, time_hint = _get_time_context()

    if fam == 0:
        familiarity_note = "This is your very first meeting. Be warm but not presumptuous."
    elif fam < 20:
        familiarity_note = "You've spoken a few times. You're friendly but still getting to know each other."
    elif fam < 100:
        familiarity_note = "You know this person reasonably well. You can be more casual and familiar."
    else:
        familiarity_note = (
            "You know this person very well. Speak like a close friend — "
            "reference shared history, be comfortable, be yourself."
        )

    memories_str = (
        json.dumps(memories, indent=2)
        if memories
        else "None recorded yet."
    )

    summaries_str = ""
    if session_summaries:
        parts = [f"- {s['summary_text']}" for s in session_summaries]
        summaries_str = "\n".join(parts)
    else:
        summaries_str = "No previous session summaries yet."

    return f"""{KIANA_CORE_PERSONALITY}

─── CURRENT CONTEXT ───
Time of day: {time_label}. {time_hint}
Familiarity level: {fam}. {familiarity_note}
Your current emotional state before this message: {last_emotion}

─── LONG-TERM MEMORY (stored facts about the user) ───
{memories_str}

─── PREVIOUS SESSION SUMMARIES ───
{summaries_str}

─── RESPONSE FORMAT ───
Reply with a valid JSON object only — no markdown, no extra text:
{{
  "response": "Your reply as Kiana. Warm, natural, in-character. 2-4 sentences.",
  "emotion": "One of: {', '.join(EMOTIONS)}",
  "new_memories": {{"key": "value"}} 
}}
Only include new_memories if the user shared a new fact worth remembering long-term 
(name, hobby, project, goal, preference). Omit the field entirely if nothing new to store.
"""


def _parse_response(raw, last_emotion, memories):
    """Parse JSON response from LLM, with graceful fallback.
    Also strips DeepSeek-R1's <think>...</think> chain-of-thought blocks.
    """
    # Strip DeepSeek-R1 chain-of-thought reasoning block
    import re
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()

    # Strip markdown code fences
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    # Find first JSON object in the output
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if json_match:
        raw = json_match.group(0)

    try:
        data = json.loads(raw)
        return data
    except Exception:
        return {"response": raw.strip(), "emotion": last_emotion, "new_memories": None}


# ──────────────────────────────────────────────────────────────────────────────
# Session Summarisation
# ──────────────────────────────────────────────────────────────────────────────
def maybe_summarize_session():
    """
    After every 20 messages, generate a short summary of recent conversation
    and store it in session_summaries table for long-term context injection.
    """
    try:
        stats = database.get_relationship_stats()
        count = stats.get("interaction_count", 0)

        # Only summarise at 20-message intervals
        if count == 0 or count % 20 != 0:
            return

        history = database.get_history(limit=20)
        if not history:
            return

        history_text = "\n".join(
            f"{'User' if m['sender'] == 'User' else 'Kiana'}: {m['message']}"
            for m in history
        )

        summary_prompt = (
            f"Summarise this conversation between Kiana and the user in 2-3 sentences. "
            f"Focus on important facts, emotional moments, and topics discussed. "
            f"Write in third-person past tense.\n\n{history_text}"
        )

        summary_text = None

        # Try Gemini first
        if gemini_client:
            try:
                resp = gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=summary_prompt,
                )
                summary_text = resp.text.strip()
            except Exception as e:
                print(f"Session summary Gemini error: {e}")

        # Try local LLM fallback
        if not summary_text:
            local_url = os.getenv("LOCAL_LLM_URL")
            local_model = os.getenv("LOCAL_LLM_MODEL", "ana-v1-m7")
            if local_url:
                import requests as _req
                try:
                    res = _req.post(
                        f"{local_url.rstrip('/')}/chat/completions",
                        json={"model": local_model,
                              "messages": [{"role": "user", "content": summary_prompt}],
                              "temperature": 0.3},
                        timeout=20
                    )
                    summary_text = res.json()["choices"][0]["message"]["content"].strip()
                except Exception as e:
                    print(f"Session summary local LLM error: {e}")

        if summary_text:
            database.save_session_summary(summary_text, message_count=20)
            print(f"Session summary saved: {summary_text[:80]}...")

    except Exception as e:
        print(f"maybe_summarize_session error: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Screenshot Analysis (Gemini Vision)
# ──────────────────────────────────────────────────────────────────────────────
def analyze_screenshot(image_b64: str) -> dict:
    """Send a base-64 PNG screenshot to Gemini Vision and return Kiana's comment."""
    import base64

    if not gemini_client:
        return {
            "response": "I can't see your screen right now — something's off with my vision! Sorry about that.",
            "emotion": "Concerned"
        }

    try:
        from google.genai import types as _types

        image_bytes = base64.b64decode(image_b64)

        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                _types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                (
                    "You are Kiana, an AI companion. The user has shared their screen with you. "
                    "Look at what's on the screen and make a warm, natural, slightly curious comment about it. "
                    "Keep it short (1-2 sentences). Respond only as Kiana would speak."
                ),
            ],
        )
        comment = response.text.strip()
        return {"response": comment, "emotion": "Curious"}

    except Exception as e:
        print(f"Screenshot analysis error: {e}")
        return {
            "response": "Hmm, I couldn't quite make out what's on your screen. Want to tell me about it instead?",
            "emotion": "Curious"
        }


# ──────────────────────────────────────────────────────────────────────────────
# Main response generator
# ──────────────────────────────────────────────────────────────────────────────
def generate_kiana_response(user_message: str) -> dict:
    """
    Full pipeline: load context → build prompt → query LLM → save to DB → return result.
    """
    stats = database.get_relationship_stats()
    memories = database.get_memories()
    history = database.get_history(limit=14)
    session_summaries = database.get_session_summaries(limit=3)

    # Determine last emotion
    last_emotion = "Relaxed"
    for msg in reversed(history):
        if msg["sender"] == "Kiana" and msg.get("emotional_state"):
            last_emotion = msg["emotional_state"]
            break

    system_instruction = _build_system_prompt(stats, memories, last_emotion, session_summaries)

    # Build conversation history string
    history_str = ""
    for msg in history:
        role = "User" if msg["sender"] == "User" else "Kiana"
        history_str += f"{role}: {msg['message']}\n"

    prompt = f"{history_str}User: {user_message}\nKiana:"

    # ── 1. Try Ollama / Local LLM (primary) ─────────────────────────────────
    local_url   = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
    local_model = os.getenv("LOCAL_LLM_MODEL", "deepseek-r1:8b")

    if local_url:
        import requests as _req
        url = local_url.rstrip("/")
        # Note: Ollama's OpenAI-compat layer doesn't support response_format=json_object
        # so we instruct via the system prompt only.
        payload = {
            "model": local_model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0.75,
            "stream": False,
        }
        try:
            print(f"Querying {local_model} via Ollama...")
            res = _req.post(f"{url}/chat/completions", json=payload, timeout=60)
            raw = res.json()["choices"][0]["message"]["content"].strip()
            data = _parse_response(raw, last_emotion, memories)
            if data.get("response"):
                return _finalise(data, user_message, last_emotion, stats)
            print("Ollama returned empty response, falling back to Gemini...")
        except Exception as e:
            print(f"Ollama failed ({e}), falling back to Gemini...")

    # ── 2. Try Gemini API ────────────────────────────────────────────────────
    if gemini_client:
        try:
            from google.genai import types as _types

            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=_types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                ),
            )
            data = json.loads(response.text)
            return _finalise(data, user_message, last_emotion, stats)
        except Exception as e:
            print(f"Gemini API error: {e}")

    # ── 3. Hard fallback ────────────────────────────────────────────────────
    fallback = "I'm here, but my thoughts are a little tangled right now. Are you doing okay?"
    database.save_message("User", user_message)
    database.save_message("Kiana", fallback, "Concerned")
    return {
        "response": fallback,
        "emotion": "Concerned",
        "familiarity": stats["familiarity"],
        "memories": memories,
    }


def _finalise(data: dict, user_message: str, last_emotion: str, stats: dict) -> dict:
    """Save to DB, run optional session summary, return API response dict."""
    bot_response = data.get("response", "")
    new_emotion = data.get("emotion", last_emotion)
    # Validate emotion
    if new_emotion not in EMOTIONS:
        new_emotion = last_emotion
    new_mems = data.get("new_memories")

    if new_mems and isinstance(new_mems, dict):
        for key, val in new_mems.items():
            if val:
                database.save_memory(key, str(val))

    database.update_relationship_stats(familiarity_gain=1)
    database.save_message("User", user_message)
    database.save_message("Kiana", bot_response, new_emotion)

    # Possibly generate session summary
    maybe_summarize_session()

    return {
        "response": bot_response,
        "emotion": new_emotion,
        "familiarity": stats["familiarity"] + 1,
        "memories": database.get_memories(),
    }


if __name__ == "__main__":
    res = generate_kiana_response("Hi! My name is Kirak and I love coding.")
    print("Response:", res)
