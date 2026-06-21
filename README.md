# Kiana AI Companion

Kiana is an intelligent desktop AI companion designed to provide natural conversations, persistent memory, voice interaction, and emotional awareness. It combines local language models with cloud AI services to create a responsive and personalized assistant.

## Features

* 🧠 Long-term memory and relationship tracking
* 💬 Natural conversational AI
* 🎤 Speech-to-Text (STT)
* 🔊 Text-to-Speech (TTS)
* 😊 Emotion-aware responses
* 📷 Screenshot analysis using Gemini Vision
* 🤖 Local LLM support through Ollama
* ☁️ Google Gemini integration
* 💾 SQLite-based memory database
* 🎭 Interactive desktop mascot with VRM avatar

---

## Tech Stack

* Python
* Flask
* SQLite
* Google Gemini API
* Ollama
* ONNX Runtime
* Kokoro TTS
* HTML / CSS / JavaScript

---

## Project Structure

```text
kiana-ai-companion/
│
├── app.py
├── memory_manager.py
├── database.py
├── mascot.py
├── wake_word.py
├── stt_manager.py
├── tts_manager.py
├── requirements.txt
├── static/
├── kokoro_models/
└── README.md
```

---

## Installation

Clone the repository:

```bash
git clone https://github.com/Kuro724/kiana-ai-companion.git
cd kiana-ai-companion
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file:

```env
GEMINI_API_KEY=your_api_key_here
LOCAL_LLM_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=deepseek-r1:8b
```

Start Ollama:

```bash
ollama serve
```

Run the application:

```bash
python app.py
```

---

## Security

Sensitive information such as API keys is **not included** in this repository.

All credentials should be stored in a local `.env` file, which is excluded from version control.

---

## Future Improvements

* Retrieval-Augmented Generation (RAG)
* Plugin ecosystem
* Offline speech recognition
* Calendar and productivity integration
* Mobile companion application
* Cross-platform installer

---

## License

This project is intended for educational, research, and personal development purposes.

---

## Author

**Peniel Chang**

Electronics & Instrumentation Engineering
National Institute of Technology Nagaland

GitHub: https://github.com/Kuro724
