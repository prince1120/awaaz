# Awaaz — Multi-Agent Voice Roundtable

A real-time, low-latency multi-agent voice discussion platform powered by **Sarvam Bulbul V4 Flash TTS**, **Sarvam Saaras STT**, and **Sarvam-105b LLM**.

Unlike single-persona voice bots, Awaaz runs live multi-character roundtables where multiple AI participants collaborate, debate, and brainstorm together in one continuous session with distinct voices and dual-layer memory.

---

## Key Features

- **Multi-Persona Voice Groups**:
  - **Office**: Manager (Rohan) & Tech Lead (Kalpit) — timelines, system architecture, deliverables, and cost.
  - **Chill**: Friend (Sunny) & Companion (Simran) — humor, creative brainstorming, and casual conversation.
  - **Family**: Mom (Shalini) & Dad (Mahesh) — health, personal care, career wisdom, and long-term discipline.
- **Distinct Voices**: Every participant is powered by a unique Sarvam Bulbul voice profile with tuned timbre, pace, and language code.
- **Sequential Turn-Taking**: Characters speak one-by-one. When addressed together or following a colleague, the second speaker responds directly to what the first speaker just stated.
- **Meeting Agenda & Grounding**: Each room includes an editable agenda that anchors character responses to the current goal.
- **Sub-Second Streaming Pipeline (< 500ms TTFA)**: Tokens stream from the LLM via HTTP/2 and pipeline immediately at clause boundaries (`.`, `!`, `?`, `,`, `।`) into TTS synthesis.
- **Instant Client-Side Barge-In**: Speaking interrupts active AI playback in under 10ms and signals the backend to halt generation.
- **Dual-Layer Memory**:
  - Global shared room transcript visible to all participants.
  - Local private stance memory per character.
  - One-click session memory purge.
- **Clean Minimal Design**: Focused, distraction-free cream theme with typographic badges and zero decorative emojis.

---

## Architecture

```
[ Browser Web Audio Client ]
  - 800ms Calibrated VAD
  - Instant Barge-in Cutoff
  - Chunked Audio Queue Player
         │
         │ Bi-directional WebSocket (/ws/voice)
         ▼
[ FastAPI Streaming Server ]
  ├── 1. STT: Sarvam Saaras (saaras:v4)
  ├── 2. Turn Orchestrator: Address detection & room routing
  ├── 3. Dual-Layer Memory: Global transcript + local persona notes
  ├── 4. HTTP/2 SSE LLM: Sarvam-105b token stream
  └── 5. Streaming Clause TTS: Sarvam Bulbul V4 Flash (< 500ms TTFA)
```

---

## Quickstart

### 1. Prerequisites
- Python 3.10+
- A valid [Sarvam AI](https://www.sarvam.ai) API key

### 2. Installation
```bash
git clone https://github.com/prince1120/awaaz.git
cd awaaz
pip install -r requirements.txt
```

### 3. Configuration
Copy `.env.example` to `.env` and provide your API key:
```bash
cp .env.example .env
```
Edit `.env`:
```env
SARVAM_API_KEY=your_actual_sarvam_api_key_here
```

### 4. Run the Application
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open `http://localhost:8000` in your browser.

---

## Docker Deployment

### Using Docker Compose
```bash
docker compose up --build
```

### Using Docker Directly
```bash
docker build -t awaaz .
docker run -p 8000:8000 --env-file .env awaaz
```

---

## Testing

Run the automated test suite:
```bash
python -m pytest -v
```

---

## Project Structure

```
awaaz/
├── app/
│   ├── __init__.py
│   ├── config.py          # Environment & Sarvam endpoints
│   ├── controller.py      # Turn-taking & address detection logic
│   ├── main.py            # FastAPI app & WebSocket voice pipeline
│   ├── personas.py        # Persona catalog, room configs & voices
│   ├── sarvam_client.py   # HTTP/2 async client for STT, LLM & TTS
│   ├── session.py         # Global & local memory management
│   └── static/
│       ├── app.js         # Web Audio client & queue player
│       ├── index.html     # Minimalist roundtable UI
│       └── styles.css     # Clean cream theme styling
├── tests/
│   └── test_controller.py # Turn-taking and memory test suite
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── LICENSE                # MIT License
└── README.md
```

---
