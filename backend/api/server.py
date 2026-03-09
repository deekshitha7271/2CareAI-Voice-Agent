import asyncio
import json
import time
import os
import logging
from typing import List, Dict, Optional
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from configs import settings
from agents.orchestrator import VoiceAIOrchestrator

# ── Logging ──
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VoiceAI.Server")

app = FastAPI(title="Clinical Voice AI Agent", version="2.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global VoiceSession Class ──
class VoiceSession:
    def __init__(self, websocket: WebSocket, session_id: str, patient_id: str, loop: asyncio.AbstractEventLoop, campaign_context: Optional[dict] = None):
        self.websocket = websocket
        self.session_id = session_id
        self.patient_id = patient_id
        self.loop = loop
        self.is_connected = True
        self.orchestrator = VoiceAIOrchestrator(session_id, patient_id, campaign_context)
        self.dg_connection = None
        self.transcript_buffer = []

    async def send_event(self, event: dict):
        if not self.is_connected:
            return
        try:
            await self.websocket.send_text(json.dumps(event))
        except Exception:
            self.is_connected = False

    async def process_and_respond(self, user_text: str, stt_ms: int = 0, is_outbound: bool = False):
        """Core pipeline: text → LLM → TTS → send events."""
        if not self.is_connected or not user_text.strip():
            return

        # 1. Update UI transcript
        if not is_outbound:
            await self.send_event({"event": "transcript", "role": "user", "text": user_text})
        
        await self.send_event({"event": "status", "state": "thinking"})

        # 2. LLM Reasoning
        t0 = time.time()

        def on_thought(txt):
            asyncio.run_coroutine_threadsafe(self.send_event({"event": "thought", "text": txt}), self.loop)

        ai_text, lang = await asyncio.to_thread(self.orchestrator.process_transcript, user_text, on_thought=on_thought)
        llm_ms = int((time.time() - t0) * 1000)
        
        # 3. Send AI Transcript
        await self.send_event({"event": "lang", "lang": lang})
        await self.send_event({"event": "transcript", "role": "agent", "text": ai_text})
        await self.send_event({"event": "status", "state": "speaking"})

        # 4. TTS (Multi-lang via Edge-TTS)
        try:
            t_tts = time.time()
            import edge_tts
            voice_map = {"hi": "hi-IN-SwaraNeural", "ta": "ta-IN-PallaviNeural", "en": "en-IN-NeerjaNeural"}
            voice = voice_map.get(lang, "en-IN-NeerjaNeural")
            
            communicate = edge_tts.Communicate(ai_text, voice)
            audio_bytes = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_bytes += chunk["data"]
            
            tts_ms = int((time.time() - t_tts) * 1000)
            if audio_bytes and self.is_connected:
                logger.info(f"[TTS] Generated {len(audio_bytes)} bytes in {tts_ms}ms. Sending to client...")
                await self.websocket.send_bytes(audio_bytes)
                await self.send_event({
                    "event": "latency", 
                    "stt_ms": stt_ms, 
                    "llm_ms": llm_ms, 
                    "tts_ms": tts_ms, 
                    "total_ms": stt_ms + llm_ms + tts_ms
                })
            else:
                logger.warning(f"[TTS] No audio generated or client disconnected. Bytes: {len(audio_bytes)}")
        except Exception as e:
            logger.error(f"[TTS] Critical Error: {e}", exc_info=True)
        
        await self.send_event({"event": "status", "state": "listening"})

class ConnectionManager:
    def __init__(self):
        self.active_sessions: dict[str, VoiceSession] = {}

    async def connect(self, session_id: str, patient_id: str, websocket: WebSocket, loop: asyncio.AbstractEventLoop, campaign_context: Optional[dict] = None):
        session = VoiceSession(websocket, session_id, patient_id, loop, campaign_context)
        self.active_sessions[session_id] = session
        return session

    def disconnect(self, session_id: str):
        if session_id in self.active_sessions:
            self.active_sessions[session_id].is_connected = False
            del self.active_sessions[session_id]

manager = ConnectionManager()

# ── API Endpoints ──
@app.get("/")
async def root():
    return {"status": "ok", "app": "Clinical Voice AI", "outbound_ready": True}

@app.post("/api/campaigns/trigger")
async def trigger_campaign(body: dict = None):
    print(f"[DEBUG] Trigger request received: {body}")
    body = body or {}
    p_id = body.get("patient_id", "Patient")
    
    if not manager.active_sessions:
        return {"status": "error", "message": "No active voice session found. Please click the orb first."}
    
    sid = list(manager.active_sessions.keys())[-1]
    session = manager.active_sessions[sid]
    
    context = None
    display_name = "Patient"

    # Quick handle for demo items (prevents DB timeouts)
    if p_id.startswith("demo_"):
        demo_map = {
            "demo_1": {"patient_name": "Aditi Sharma", "doctor_name": "Dr. Miku", "date_str": "Tomorrow", "time_str": "10:00 AM"},
            "demo_hi": {"patient_name": "Rajesh Kumar", "doctor_name": "Dr. Pallavi", "date_str": "Monday", "time_str": "02:00 PM"},
            "demo_ta": {"patient_name": "M. Thamil", "doctor_name": "Dr. Pallavi", "date_str": "Tomorrow", "time_str": "09:00 AM"}
        }
        context = demo_map.get(p_id, {"patient_name": "Aditi", "doctor_name": "Dr. Miku", "date_str": "tomorrow", "time_str": "10am"})
        display_name = context["patient_name"]
        print(f"[DEBUG] Using demo context for {p_id}")
    else:
        # Resolve real clinical context from DB
        try:
            from memory.database import get_db
            from bson.objectid import ObjectId
            db = get_db()
            if db and len(p_id) == 24:
                appt = db.appointments.find_one({"_id": ObjectId(p_id)})
                if appt:
                    context = {
                        "appointment_id": str(appt["_id"]),
                        "patient_name": appt["patient_name"],
                        "doctor_name": appt["doctor_name"],
                        "date_str": appt["date_str"],
                        "time_str": appt["time_str"]
                    }
                    display_name = appt["patient_name"]
                    print(f"[DEBUG] Resolved real DB context for {p_id}")
        except Exception as e:
            logger.warning(f"DB resolution failed: {e}")

    # Final fallback if still no context
    if not context:
        context = {"patient_name": "the patient", "doctor_name": "the doctor", "date_str": "today", "time_str": "now"}
        display_name = "Patient"

    # 2. Inject context into the LIVE orchestrator & force memory clean for the new patient
    session.orchestrator.set_campaign_context(context, new_patient_id=p_id)
    session.patient_id = p_id
    
    initial_msg = f"Hello {display_name}! This is 2Care AI calling regarding your clinical appointment. How are you?"
    asyncio.create_task(session.process_and_respond(initial_msg, is_outbound=True))
    
    return {"status": "started", "message": f"Campaign initiated for {display_name}"}

@app.get("/api/patients")
async def get_patients():
    """Returns real virtual clinic tasks (Campaigns) from the DB."""
    tasks = []
    try:
        from memory.database import get_db
        db = get_db()
        if db is not None:
            # Fetch booked appointments for the next 48 hours
            from datetime import datetime, timedelta
            now = datetime.utcnow()
            future = now + timedelta(hours=48)
            
            cursor = db.appointments.find({
                "status": "Booked",
                "appointment_time": {"$gte": now, "$lte": future}
            }).sort("appointment_time", 1).limit(5)
            
            for doc in cursor:
                tasks.append({
                    "id": str(doc["_id"]),
                    "name": f"Remind: {doc['patient_name']} ({doc['doctor_name']})",
                    "type": "reminder"
                })
    except Exception as e:
        logger.error(f"[API] Error fetching clinic tasks: {e}")

    # Fallback/Demo items
    if len(tasks) < 3:
        demo_items = [
            {"id": "demo_1", "name": "Remind: Aditi Sharma (Demo)"},
            {"id": "demo_hi", "name": "Reschedule: Rajesh Kumar (Demo)"},
            {"id": "demo_ta", "name": "Confirm: M. Thamil (Demo)"}
        ]
        tasks.extend(demo_items)

    return {"patients": tasks[:8]}

# ── WebSocket Handler ──
import time
@app.websocket("/ws/voice")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = f"sess_{int(time.time())}"
    # Default patient ID for inbound/demo chat
    patient_id = "demo_patient_1"
    
    loop = asyncio.get_event_loop()
    session = await manager.connect(session_id, patient_id, websocket, loop)
    
    logger.info(f"[WS] Session {session_id} connected")

    # 1. Setup Deepgram
    from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
    try:
        dg_client = DeepgramClient(api_key=os.getenv("DEEPGRAM_API_KEY", ""))
        dg_connection = dg_client.listen.websocket.v("1")

        def on_message(self, result, **kwargs):
            transcript = result.channel.alternatives[0].transcript
            if not transcript: return
            if result.is_final:
                session.transcript_buffer.append(transcript)
            if result.speech_final:
                final_text = " ".join(session.transcript_buffer).strip()
                session.transcript_buffer.clear()
                if final_text:
                    logger.info(f"[STT] Final: {final_text}")
                    asyncio.run_coroutine_threadsafe(session.process_and_respond(final_text), loop)

        dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
        options = LiveOptions(model="nova-2", language="multi", smart_format=True, encoding="linear16", channels=1, sample_rate=48000, endpointing=300)
        dg_connection.start(options)
        session.dg_connection = dg_connection
    except Exception as e:
        logger.warning(f"[STT] Deepgram initialization failed: {e}")

    # 2. Receive Loop
    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect": break
            
            if "bytes" in msg and session.dg_connection:
                session.dg_connection.send(msg["bytes"])
            elif "text" in msg:
                data = json.loads(msg["text"])
                if data.get("text"):
                    await session.process_and_respond(data["text"])
    except Exception as e:
        logger.error(f"[WS] Error: {e}")
    finally:
        if session.dg_connection:
            try: dg_connection.finish()
            except: pass
        manager.disconnect(session_id)
        logger.info(f"[WS] Session {session_id} disconnected")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True)
