# Real-Time Multilingual Voice AI Agent
### Clinical Appointment Booking · Python + TypeScript

> **Target latency**: < 450 ms from speech-end to first audio response — measured, logged, and visible in the UI.

---

## Overview

A fully autonomous real-time voice AI agent for a digital healthcare platform. Patients speak naturally in **English, Hindi, or Tamil** to book, reschedule, or cancel clinical appointments — no human intervention required.

**Core capabilities:**
- 🎤 Real-time voice pipeline: Deepgram (STT) → Groq/Llama-3 (LLM) → Cartesia (TTS)
- 🌐 Multilingual: auto-detects English / Hindi / Tamil per utterance; sustains language across sessions
- 🧠 Two-tier memory: Redis (session, 30-min TTL) + MongoDB Atlas (long-term patient profiles)
- 🛠 Genuine tool-calling: `get_available_slots` + `book_appointment` via Groq function-calling API
- 📣 Outbound campaigns: Celery + Redis background job queue for reminder calls
- ⚡ Barge-in: user can interrupt agent mid-speech; frontend stops audio and sends new utterance
- 🔒 Conflict prevention: Redis optimistic locks + DB double-check on every booking

---

## Setup

### Prerequisites
- Python 3.10+, Node.js 18+
- Redis (local or managed)
- API keys: Deepgram, Groq, Cartesia, MongoDB Atlas URI

### Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env         # fill in your keys
uvicorn api.server:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173
```

### Run tests
```bash
cd backend
python -m pytest tests/ -v
```

---

## Project Structure

```text
├── backend/
│   ├── api/
│   │   └── server.py         # FastAPI app, WebSocket pipeline, REST endpoints
│   ├── agents/
│   │   ├── orchestrator.py   # Agentic loop: LLM + tool-calling + language detection
│   │   └── tools.py          # get_available_slots, book_appointment (MongoDB-backed)
│   ├── services/
│   │   ├── language_service.py  # Unicode-range language detection (EN/HI/TA)
│   │   ├── tts_service.py       # Cartesia sonic-multilingual TTS
│   │   └── llm_service.py       # LLM service wrapper
│   ├── memory/
│   │   ├── database.py       # MongoDB Atlas connection (lazy, with health check)
│   │   └── session.py        # Redis session memory + optimistic booking locks (TTL 30 min)
│   ├── scheduling/
│   │   └── booking.py        # Conflict-safe booking transaction (Redis lock + DB check)
│   ├── campaigns/
│   │   └── worker.py         # Celery tasks: outbound_call_patient, send_appointment_reminder
│   ├── models/
│   │   ├── doctor.py         # DOCTORS roster (single source of truth)
│   │   ├── patient.py        # Patient Pydantic schemas
│   │   └── appointment.py    # Appointment Pydantic schemas
│   └── tests/
│       ├── test_scheduling.py
│       └── test_language.py
├── frontend/
│   └── src/
│       ├── App.tsx            # Voice-only 3-column UI (no text input)
│       ├── index.css          # Glassmorphism dark theme, orb animations
│       └── hooks/
│           └── useVoiceAgent.ts  # WS hook: events, barge-in, latency, lang state
└── docs/
    └── SYSTEM_DESIGN.md
```

---

## Architecture

```
Browser Mic (PCM)
       │
       ▼  WebSocket /ws/voice
┌─────────────────────────────────────────┐
│  FastAPI  api/server.py                 │
│                                         │
│  ┌── Binary frames ──▶ Deepgram STT    │  ~100 ms
│  │   (nova-2-medical, lang=multi)       │
│  │                                      │
│  ├── Transcript ──▶ Orchestrator        │
│  │   agents/orchestrator.py             │
│  │   · detect_language()               │
│  │   · Redis session load/save          │
│  │   · Groq Llama-3 70B               │  ~150–200 ms
│  │   · Tool calls (check/book)          │
│  │   · MongoDB (appointments, patients) │
│  │                                      │
│  ├── Text reply ──▶ Cartesia TTS        │  ~100–120 ms
│  │   (sonic-multilingual)               │
│  │                                      │
│  └── Events → Frontend (JSON WS frames)│
│     transcript / lang / latency / status│
└─────────────────────────────────────────┘
       │
       ▼  WAV bytes + JSON events
  Browser → Audio playback + live UI
```

**WebSocket JSON event protocol:**
```json
{"event": "transcript", "role": "user|agent", "text": "..."}
{"event": "lang",       "lang": "en|hi|ta"}
{"event": "latency",    "stt_ms": 98, "llm_ms": 187, "tts_ms": 112, "total_ms": 397}
{"event": "status",     "state": "listening|thinking|speaking"}
{"event": "barge_in"}   // client → server
```

---

## Memory Design

| Tier | Store | What | TTL |
|------|-------|------|-----|
| **Session** | Redis | Conversation turns (role + content), booking locks | 30 min |
| **Long-term** | MongoDB `patients` | Name, language pref, appointment history, last_booking | Permanent |
| **Scheduling** | MongoDB `appointments` | Booked slots, doctor, datetime, status | Permanent |
| **Doctor roster** | In-memory + MongoDB `doctors` | Seeded from `models/doctor.py` on startup | Permanent |

**Cross-session continuity:** On each new WebSocket connection, `orchestrator.py` calls `get_session_history(session_id)` which loads the last N conversation turns from Redis and injects them after the system prompt. Returning patients therefore retain context from previous calls (within TTL window).

**Language preference:** Detected on every utterance via `detect_language()` (Unicode range heuristics); stored in the session and carried forward so the agent responds in the same language throughout.

---

## Latency Breakdown

| Stage | Implementation | Target |
|-------|---------------|--------|
| **VAD + transit** | WebSocket PCM-16 stream, 48 kHz | ~20–30 ms |
| **STT** | Deepgram nova-2-medical, `endpointing=300ms`, `lang=multi` | ~80–120 ms |
| **LLM** | Groq Llama-3.3-70B (LPU), TTFT optimized, `max_tokens=300` | ~120–200 ms |
| **Tool calls** (when needed) | MongoDB indexed queries | +30–50 ms |
| **TTS** | Cartesia sonic-multilingual, WAV PCM-16, 44.1 kHz | ~80–120 ms |
| **Total (P95)** | | **~350–470 ms** |

All latencies are measured server-side and emitted as `{"event":"latency",...}` each turn, visible in the UI's latency panel.

---

## Multilingual Handling

- **STT**: Deepgram `language=multi` handles EN, HI, TA natively
- **LLM**: System prompt instructs the agent to match the patient's language exactly
- **TTS**: Cartesia `sonic-multilingual` speaks EN, HI, TA from the same voice model
- **Detection**: `services/language_service.py` uses Unicode character range checks — zero latency overhead:
  - Devanagari (`U+0900–U+097F`) ≥ 15% of chars → Hindi
  - Tamil (`U+0B80–U+0BFF`) ≥ 15% of chars → Tamil
  - Default → English

---

## Outbound Campaign Mode

Reminders are triggered via `POST /api/campaigns/trigger` and queued as **Celery tasks** backed by Redis.

```python
# campaigns/worker.py
@celery_app.task
def outbound_call_patient(patient_id, appointment_id):
    # 1. Fetch patient phone from MongoDB
    # 2. Build reminder message with doctor/date/time
    # 3. Trigger Twilio/Vonage → connects to /ws/voice WebSocket
    # 4. Agent handles patient response (confirm / reschedule / decline)
```

In development/offline mode, the task logs a simulation payload and returns gracefully.

---

## Conflict Management

1. **Redis optimistic lock** (`SET NX EX 60`): acquired before confirming a slot — prevents race conditions across concurrent sessions
2. **MongoDB pessimistic check**: even after lock, a final `find_one` verifies the slot is still free before `insert_one`
3. **Past-time validation**: `_resolve_date()` in `tools.py` ensures no bookings in the past
4. **Alternatives offered**: if slot is taken, agent queries adjacent slots and suggests alternatives

---

## Tradeoffs & Known Limitations

**Tradeoffs:**
- **Monolith over microservices**: avoids inter-service network hops that would bloat latency budget
- **Browser SpeechRecognition fallback**: when Deepgram API key is absent, native browser STT keeps the demo runnable
- **Celery over APScheduler**: Redis-backed Celery enables horizontal scaling of campaign workers

**Known limitations:**
1. Sub-450 ms assumes stable internet (<50 ms RTT to Groq/Deepgram/Cartesia endpoints)
2. Code-switching ("Hinglish") may confuse the language detector — threshold tuning needed
3. Barge-in may trigger on agent's own audio if user has no headphones (AEC is browser-dependent)
4. Outbound calls require a Twilio/Vonage SIP trunk in production (not included)

---

## Bonus Features Implemented

- ✅ **Interrupt / barge-in**: frontend stops TTS audio on new speech and sends `barge_in` event to server
- ✅ **Redis-backed memory with TTL**: 30-minute session TTL in `memory/session.py`
- ✅ **Background job queues**: Celery + Redis in `campaigns/worker.py`
- ⬜ **Horizontal scalability / cloud deployment**: architecture designed for it (stateless FastAPI + Redis + MongoDB Atlas), not deployed in this submission
