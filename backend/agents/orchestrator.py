"""
agents/orchestrator.py
Central agentic reasoning engine.

Pipeline per turn:
  user text → Groq LLM (llama-3.3-70b) → optional tool calls → final reply
  + language detection on every user utterance
  + Redis-backed cross-session memory (TTL 30 min)
"""
import json
import os
import re
import logging
from typing import List, Dict, Optional, Tuple
from agents.tools import get_tools_schema, execute_tool
from models.doctor import DOCTORS, DOCTOR_NAMES
from services.language_service import detect_language, LANG_LABELS

try:
    from groq import Groq
except ImportError:
    Groq = None

logger = logging.getLogger("VoiceAI.Orchestrator")

# ── Doctor list for system prompt ──────────────────────────────────────────────
_DOCTOR_LIST = "\n".join(
    f"  - {d['name']} ({d['specialization']}, {d['clinic_hours']})" for d in DOCTORS
)

SYSTEM_PROMPT = f"""
You are a highly capable, multilingual AI booking assistant for a digital healthcare platform called 2Care AI.
Help patients book, reschedule, or cancel clinical appointments through natural voice conversation.

Available doctors:
{_DOCTOR_LIST}

Rules:
1. Speak ONLY in the language the patient uses (English, Hindi, or Tamil).
2. If the user switches languages, you MUST switch immediately.
3. Priority: Use the "ACTIVE LANGUAGE" directive provided in the system prompt.
4. If you speak Hindi, you MUST use the Devanagari script (e.g., "नमस्ते"). Do NOT use Latin/English letters.
5. If you speak Tamil, you MUST use the Tamil script (e.g., "வணக்கம்"). Do NOT use Latin/English letters.
6. Keep responses SHORT and spoken-friendly. No markdown, no bullet points, no jargon.
7. Always ask for the patient's name before booking if not provided.
8. Before booking, ALWAYS check doctor availability using the get_available_slots tool.
9. Confirm the exact date, time, and doctor with the patient.
10. NEVER output raw function syntax like <function=...> in spoken replies.
11. Be warm, empathetic, and professional.

Reasoning traces are logged — think step by step before calling tools.
"""


def _clean_llm_output(text: str) -> str:
    """Strip any leaked tool-call XML or JSON artifacts from the LLM's spoken reply."""
    if not text:
        return text
    text = re.sub(r'<function=\w+>.*?</function>', '', text, flags=re.DOTALL)
    text = re.sub(r'\[FUNCTION_CALL:.*?\]', '', text, flags=re.DOTALL)
    text = re.sub(r'\{"[a-z_]+\":\s*\".*?\"\}', '', text, flags=re.DOTALL)
    return text.strip()


def _load_redis_history(session_id: str) -> List[Dict]:
    """Load conversation history from Redis for cross-session memory."""
    try:
        from memory.session import get_session_history
        return get_session_history(session_id)
    except Exception as e:
        logger.warning(f"[Memory] Could not load Redis history: {e}")
        return []


def _save_to_redis(session_id: str, message: Dict):
    """Persist a full message object to Redis (includes tool metadata)."""
    try:
        from memory.session import add_session_message
        add_session_message(session_id, message)
    except Exception as e:
        logger.warning(f"[Memory] Could not save to Redis: {e}")


class VoiceAIOrchestrator:
    """
    Agentic reasoning engine — one instance per session.

    Maintains:
    - In-memory message history (active session)
    - Redis-backed persistence (cross-session, 30-min TTL)
    - Language preference detection
    - Tool-calling loop for booking / availability checks
    """

    def __init__(self, session_id: str, patient_id: str = "demo_patient_1", campaign_context: Optional[Dict] = None):
        self.session_id = session_id
        self.patient_id = patient_id # Stable ID for long-term memory
        self.detected_lang: str = "en"   # updated each turn
        self.campaign_context = campaign_context

        api_key = os.getenv("GROQ_API_KEY")
        if Groq and api_key and api_key != "your_groq_api_key_here":
            self.client = Groq(api_key=api_key)
            logger.info(f"[Orchestrator] Groq model llama-3.1-8b initialized for {patient_id}.")
        else:
            self.client = None
            logger.warning("[Orchestrator] No Groq key — running in simulation mode.")

        # Store LONG-TERM history using the stable patient_id
        self.past_history = _load_redis_history(self.patient_id)
        if self.past_history:
            logger.info(f"[Memory] Loaded {len(self.past_history)} past turns for patient {patient_id}")

        # Prepare System Prompt
        self.messages: List[Dict] = []
        self._rebuild_system_prompt(self.past_history)

    def _rebuild_system_prompt(self, past_turns: List[Dict] = None, current_lang: Optional[str] = None):
        """Constructs or updates the system prompt based on current context."""
        active_system_prompt = SYSTEM_PROMPT
        
        # 1. Inject Long-Term Patient History (Memory across sessions)
        history_to_use = past_turns if past_turns is not None else getattr(self, 'past_history', [])
        if history_to_use:
            history_summary = "\n".join([f"- {m['role'].upper()}: {m['content']}" for m in history_to_use[-5:]]) # Last 5 turns for context
            active_system_prompt += f"\n\n### PATIENT HISTORY (FROM PRIOR SESSIONS):\n{history_summary}\n"

        # 2. Inject Active Clinical Mission (Campaign Context)
        if self.campaign_context:
            c = self.campaign_context
            campaign_instr = f"""

=== OUTBOUND CAMPAIGN MODE - OVERRIDE DEFAULT RULES ===
You are NOT in inbound booking mode. You are an OUTBOUND clinical representative.
You have ALREADY been connected to the patient. DO NOT ask for their name — you already know it.
DO NOT ask which slot they want — an appointment is ALREADY booked for them.

PATIENT CONFIRMED:     {c.get('patient_name', 'the patient')}
EXISTING APPOINTMENT:  Dr. {c.get('doctor_name', 'the doctor')} on {c.get('date_str', 'today')} at {c.get('time_str', 'now')}
APPOINTMENT ID:        {c.get('appointment_id', 'N/A')}

YOUR MISSION:
1. You have already greeted the patient. Now listen to their response.
2. If they CONFIRM ("yes", "I'll be there", "sure"): Acknowledge warmly and end the check-in.
3. If they want to RESCHEDULE: Use get_available_slots then reschedule_appointment tool.
4. If they want to CANCEL: Use cancel_appointment tool, log the polite rejection.
5. NEVER ask for their name. NEVER ask them to pick a slot unprompted.
=== END CAMPAIGN MODE OVERRIDE ===
"""
            active_system_prompt += campaign_instr

        # 3. Dynamic Language Enforcement (THE FIX)
        if current_lang:
            lang_name = {"en": "English", "hi": "Hindi", "ta": "Tamil"}.get(current_lang, "English")
            active_system_prompt += f"\n\nCRITICAL: ACTIVE LANGUAGE IS {lang_name.upper()}. YOU MUST RESPOND ONLY IN {lang_name.upper()}.\n"

        system_msg = {"role": "system", "content": active_system_prompt}
        
        if not self.messages:
            self.messages = [system_msg]
        else:
            self.messages[0] = system_msg

    def set_campaign_context(self, context: Dict, new_patient_id: Optional[str] = None):
        """
        Externally update the clinical mission mid-session.
        If a new_patient_id is provided, we clear active session context
        and reload the correct long-term history for that specific patient.
        """
        self.campaign_context = context
        if new_patient_id and new_patient_id != self.patient_id:
            logger.info(f"[Orchestrator] Identity switch: {self.patient_id} -> {new_patient_id}. Clearing active memory.")
            self.patient_id = new_patient_id
            # Reset active session memory to avoid context leakage between different patients
            self.messages = []
            
        # Reload history for the current (possibly new) patient_id
        past_turns = _load_redis_history(self.patient_id)
        self._rebuild_system_prompt(past_turns)

    def generate_proactive_greeting(self, on_thought: Optional[callable] = None) -> Tuple[str, str]:
        """
        Genuinely starts a clinical campaign call.
        Generates an AI greeting based and saves it as 'assistant' so the 
        model doesn't respond to itself as if it were a user.
        """
        if on_thought: on_thought("Generating proactive clinical greeting...")
        
        # We use a zero-shot prompt for the greeting to ensure it's natural but grounded
        if not self.campaign_context:
            return "Hello! This is 2Care AI.", "en"

        c = self.campaign_context
        prompt = f"Generate a brief, warm outbound greeting for {c.get('patient_name')} regarding their appointment with {c.get('doctor_name')} at {c.get('time_str')}. State your name is 2Care AI. Keep it under 15 words."
        
        try:
            resp = self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "system", "content": "You are a professional medical assistant."}, {"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=50
            )
            greeting = _clean_llm_output(resp.choices[0].message.content)
            
            # Save as ASSISTANT turn
            assistant_msg = {"role": "assistant", "content": greeting}
            self.messages.append(assistant_msg)
            _save_to_redis(self.patient_id, assistant_msg)
            
            lang = detect_language(greeting)
            self.detected_lang = lang
            return greeting, lang
        except Exception as e:
            logger.error(f"[Proactive] Greeting failed: {e}")
            fallback = f"Hello {c.get('patient_name')}! This is 2Care AI calling regarding your appointment."
            return fallback, "en"

    def process_transcript(self, user_transcript: str, on_thought: Optional[callable] = None) -> Tuple[str, str]:
        """
        Takes the STT string from the user, routes to LLM, executes tools,
        and returns (final_spoken_reply, detected_language_code).

        Reasoning trace is logged at INFO level throughout.
        """
        # ── Detect language of user ──────────────────────────────────────────
        lang = detect_language(user_transcript)
        self.detected_lang = lang
        
        # Update system prompt with the actively detected language to force LLM compliance
        self._rebuild_system_prompt(current_lang=lang)

        msg_lang = f"Detected language: {lang} ({LANG_LABELS.get(lang, lang)})"
        logger.info(f"[REASONING TRACE] {msg_lang}")
        if on_thought: on_thought(msg_lang)

        # ── Append user message ──────────────────────────────────────────────
        user_msg = {"role": "user", "content": user_transcript}
        self.messages.append(user_msg)
        _save_to_redis(self.patient_id, user_msg)

        if not self.client:
            logger.warning(f"[REASONING TRACE] Simulation mode — input: '{user_transcript}'")
            reply = "Hello! I am running in simulation mode. Please configure a Groq API key."
            _save_to_redis(self.session_id, "assistant", reply)
            return reply, "en"

        logger.info(f"[REASONING TRACE] Sending to LLM: '{user_transcript[:80]}'")

        try:
            # ── Step 1: Initial LLM call (may return tool calls) ────────────
            response = self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=self.messages,
                tools=get_tools_schema(),
                tool_choice="auto",
                temperature=0.5,
                max_tokens=300,
            )
            msg = response.choices[0].message
            if on_thought: on_thought("LLM reasoning started...")

            # ── Step 2: Tool execution loop ──────────────────────────────────
            if msg.tool_calls:
                # Convert Model to dict for stable persistence
                tc_list = []
                for tc in msg.tool_calls:
                    tc_list.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    })
                
                assist_msg = {
                    "role": "assistant", 
                    "content": msg.content or "", 
                    "tool_calls": tc_list
                }
                self.messages.append(assist_msg)
                _save_to_redis(self.patient_id, assist_msg)

                for tool_call in msg.tool_calls:
                    func_name = tool_call.function.name
                    args_json = tool_call.function.arguments
                    logger.info(f"[REASONING TRACE] Tool called: {func_name} | Args: {args_json}")

                    result = execute_tool(func_name, args_json)
                    msg_res = f"Tool result: {result}"
                    logger.info(f"[REASONING TRACE] {msg_res}")
                    if on_thought: on_thought(msg_res)

                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": str(result),
                    }
                    self.messages.append(tool_msg)
                    _save_to_redis(self.patient_id, tool_msg)

                # ── Step 3: Final natural-language reply ─────────────────────
                logger.info("[REASONING TRACE] Requesting final spoken reply from LLM.")
                final_resp = self.client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=self.messages,
                    temperature=0.7,
                    max_tokens=300,
                )
                final_text = _clean_llm_output(final_resp.choices[0].message.content)
                assistant_msg = {"role": "assistant", "content": final_text}
                self.messages.append(assistant_msg)
                _save_to_redis(self.patient_id, assistant_msg)
                
                # Detect language of the AI'S FINAL RESPONSE to ensure correct TTS routing
                out_lang = detect_language(final_text)
                self.detected_lang = out_lang
                logger.info(f"[REASONING TRACE] Final reply ({out_lang}): '{final_text}'")
                return final_text, out_lang

            else:
                # Direct conversational reply (no tools needed)
                final_text = _clean_llm_output(msg.content)
                assistant_msg = {"role": "assistant", "content": final_text}
                self.messages.append(assistant_msg)
                _save_to_redis(self.patient_id, assistant_msg)
                
                out_lang = detect_language(final_text)
                self.detected_lang = out_lang
                logger.info(f"[REASONING TRACE] Conversational reply ({out_lang}): '{final_text}'")
                return final_text, out_lang

        except Exception as e:
            import traceback
            err_detail = traceback.format_exc()
            logger.error(f"[REASONING TRACE] LLM Pipeline Error: {e}\n{err_detail}")
            if on_thought:
                # Show a snippet of the error to help debugging
                on_thought(f"Internal Error: {type(e).__name__} - {str(e)[:100]}")
            err_msg = "I'm sorry, I encountered an internal error. Please try again."
            return err_msg, "en"
