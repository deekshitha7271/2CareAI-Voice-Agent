"""
tools.py — Real MongoDB-backed tool implementations for the Voice AI Agent.

The LLM calls these functions via the function-calling API.
Data is persisted to MongoDB Atlas (appointments + doctors collections).
"""

from typing import Dict, Any, List
import json
import logging
from datetime import datetime, timedelta
from models.doctor import DOCTORS, DOCTOR_NAMES
from scheduling.booking import (
    process_booking_transaction, 
    cancel_appointment_transaction, 
    reschedule_appointment_transaction
)

logger = logging.getLogger("VoiceAI.Tools")

_db_loaded = False
_db = None

def _get_db():
    global _db, _db_loaded
    if not _db_loaded:
        _db_loaded = True
        try:
            from memory.database import get_db
            _db = get_db()  # Returns None if Atlas is unreachable
            if _db is not None:
                _ensure_seed_data(_db)
        except Exception as e:
            logger.warning(f"[Tools] DB import failed: {e}")
            _db = None
    return _db


def _ensure_seed_data(db):
    """
    Seed a minimal set of doctors into the DB on first run
    so the agent has real data to work with.
    """
    # Sync doctor roster from models.doctor (single source of truth)
    for doc in DOCTORS:
        db.doctors.update_one(
            {"name": doc["name"]},
            {"$set": doc},
            upsert=True
        )
    logger.info("[DB] Doctor roster synced (%d doctors).", len(DOCTORS))


# ──────────────────────────────────────────────────────────────────────────────
# Helper: resolve relative dates
# ──────────────────────────────────────────────────────────────────────────────
def _resolve_date(date_str: str) -> str:
    """Convert natural words to YYYY-MM-DD."""
    today = datetime.now().date()
    d = date_str.lower().strip()
    if d in ("today", "aaj", "இன்று"):
        return str(today)
    if d in ("tomorrow", "kal", "நாளை"):
        return str(today + timedelta(days=1))
    # Try to parse directly
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Fallback: assume tomorrow
    return str(today + timedelta(days=1))


# ──────────────────────────────────────────────────────────────────────────────
# Tool 1: Check availability
# ──────────────────────────────────────────────────────────────────────────────
def get_available_slots(doctor_name: str, date: str) -> str:
    """Query MongoDB for booked slots and return the free ones."""
    db = _get_db()
    resolved_date = _resolve_date(date)

    if db is None:
        # Graceful fallback without crashing
        return f"Available slots for {doctor_name} on {resolved_date}: 09:00 AM, 11:00 AM, 02:00 PM."

    try:
        # Find the doctor document
        doctor = db.doctors.find_one({"name": {"$regex": doctor_name, "$options": "i"}})
        if not doctor:
            names = ", ".join(DOCTOR_NAMES)
            return f"No doctor named '{doctor_name}' found. Available: {names}."

        # Build date range for the day
        date_obj = datetime.strptime(resolved_date, "%Y-%m-%d")
        day_start = date_obj.replace(hour=0, minute=0, second=0)
        day_end   = date_obj.replace(hour=23, minute=59, second=59)

        # Query booked appointments for this doctor on this day
        booked = list(db.appointments.find({
            "doctor_name": doctor["name"],
            "appointment_time": {"$gte": day_start, "$lte": day_end},
            "status": "Booked"
        }))
        booked_times = {appt["appointment_time"].strftime("%I:%M %p") for appt in booked}

        # All hourly slots 9 AM – 4 PM
        all_slots = []
        for h in range(9, 17):
            suffix = "AM" if h < 12 else "PM"
            hr = h if h <= 12 else h - 12
            all_slots.append(f"{hr}:00 {suffix}")
            
        free_slots = [s for s in all_slots if s not in booked_times]

        if not free_slots:
            return f"Dr. {doctor['name']} is fully booked on {resolved_date}. Would you like to check another date?"

        slots_str = ", ".join(free_slots)
        logger.info(f"[DB] Availability check: {doctor['name']} on {resolved_date} → {len(free_slots)} free slots")
        return f"Available slots for {doctor['name']} on {resolved_date}: {slots_str}."

    except Exception as e:
        logger.error(f"[DB] get_available_slots error: {e}")
        return f"Could not fetch slots for {doctor_name}. Please try again."


# ──────────────────────────────────────────────────────────────────────────────
# Tool 2: Book appointment (WRITES to MongoDB)
# ──────────────────────────────────────────────────────────────────────────────
def book_appointment(patient_name: str, doctor_name: str, date: str, time: str) -> str:
    """
    Inserts a new appointment document into MongoDB.
    Also checks for double-booking before inserting.
    """
    resolved_date = _resolve_date(date)

    try:
        # Parse appointment datetime robustly
        time_clean = time.strip().upper()
        import re
        # Normalizes "9 AM" to "9:00 AM" so date parser doesn't fail
        time_clean = re.sub(r'^(\d{1,2})\s*(AM|PM)$', r'\1:00 \2', time_clean)
        
        try:
            from dateutil import parser
            appt_dt = parser.parse(f"{resolved_date} {time_clean}")
        except Exception:
            try:
                appt_dt = datetime.strptime(f"{resolved_date} {time_clean}", "%Y-%m-%d %I:%M %p")
            except ValueError:
                # Store as text if parsing fails
                appt_dt = datetime.strptime(resolved_date, "%Y-%m-%d")

        # Delegate the actual transaction to our dedicated scheduling service
        # This keeps our 'tools' layer clean and focused only on the LLM interface.
        return process_booking_transaction(
            patient_name=patient_name,
            doctor_name=doctor_name,
            date_str=resolved_date,
            time_str=time_clean,
            appt_dt=appt_dt,
            session_id="voice_session" # In production, this comes from the orchestrator
        )

    except Exception as e:
        logger.error(f"[Tools] book_appointment entry error: {e}")
        return f"Failed to process the booking request: {str(e)}"


# ──────────────────────────────────────────────────────────────────────────────
# Tool 3: Cancel appointment
# ──────────────────────────────────────────────────────────────────────────────
def cancel_appointment(appointment_id: str) -> str:
    """Cancels a specific appointment in the database."""
    return cancel_appointment_transaction(appointment_id)


# ──────────────────────────────────────────────────────────────────────────────
# Tool 4: Reschedule appointment
# ──────────────────────────────────────────────────────────────────────────────
def reschedule_appointment(appointment_id: str, new_date: str, new_time: str) -> str:
    """Moves an existing appointment to a new date and time."""
    resolved_date = _resolve_date(new_date)
    
    # Simple time normalization
    time_clean = new_time.strip().upper()
    import re
    time_clean = re.sub(r'^(\d{1,2})\s*(AM|PM)$', r'\1:00 \2', time_clean)

    from dateutil import parser
    try:
        new_dt = parser.parse(f"{resolved_date} {time_clean}")
    except Exception:
        new_dt = datetime.strptime(resolved_date, "%Y-%m-%d")

    return reschedule_appointment_transaction(
        appointment_id=appointment_id,
        new_date_str=resolved_date,
        new_time_str=time_clean,
        new_appt_dt=new_dt,
        session_id="voice_session"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Tool schema for LLM function calling (unchanged interface)
# ──────────────────────────────────────────────────────────────────────────────
def get_tools_schema() -> List[Dict[str, Any]]:
    """Returns the JSON schema for LLM function calling."""
    return [
        {
            "type": "function",
            "function": {
                "name": "get_available_slots",
                "description": "Check what time slots are available for a specific doctor on a specific date. Call this BEFORE booking.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "doctor_name": {
                            "type": "string",
                            "description": "The full name of the doctor (e.g. Dr. Smith, Dr. Sharma, Dr. Kumar)"
                        },
                        "date": {
                            "type": "string",
                            "description": "The date to check. Use YYYY-MM-DD format or words like 'today', 'tomorrow'"
                        }
                    },
                    "required": ["doctor_name", "date"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "book_appointment",
                "description": "Book a confirmed appointment for a patient. Only call this after the patient confirms the slot.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_name": {
                            "type": "string",
                            "description": "Full name of the patient"
                        },
                        "doctor_name": {
                            "type": "string",
                            "description": "Full name of the doctor (e.g. Dr. Smith)"
                        },
                        "date": {
                            "type": "string",
                            "description": "Date of the appointment in YYYY-MM-DD, or 'today'/'tomorrow'"
                        },
                        "time": {
                            "type": "string",
                            "description": "Time of the appointment, e.g. '09:00 AM', '02:00 PM'"
                        }
                    },
                    "required": ["patient_name", "doctor_name", "date", "time"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_appointment",
                "description": "Cancel an existing appointment. Use this if the patient specifically requests to cancel their visit.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "appointment_id": {
                            "type": "string",
                            "description": "The unique ID of the appointment to cancel."
                        }
                    },
                    "required": ["appointment_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "reschedule_appointment",
                "description": "Move an existing appointment to a new date or time.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "appointment_id": {
                            "type": "string",
                            "description": "The unique ID of the existing appointment."
                        },
                        "new_date": {
                            "type": "string",
                            "description": "The new target date (YYYY-MM-DD or words like 'tomorrow')."
                        },
                        "new_time": {
                            "type": "string",
                            "description": "The new target time (e.g., '11:00 AM')."
                        }
                    },
                    "required": ["appointment_id", "new_date", "new_time"]
                }
            }
        }
    ]


def execute_tool(func_name: str, arguments_json: str) -> str:
    """Executes the tool requested by the LLM and returns its string result."""
    try:
        args = json.loads(arguments_json)
    except json.JSONDecodeError:
        return "Error: Could not parse tool arguments."

    if func_name == "get_available_slots":
        return get_available_slots(
            args.get("doctor_name", ""),
            args.get("date", "today")
        )
    elif func_name == "book_appointment":
        return book_appointment(
            args.get("patient_name", "Patient"),
            args.get("doctor_name", ""),
            args.get("date", "today"),
            args.get("time", "")
        )
    elif func_name == "cancel_appointment":
        return cancel_appointment(args.get("appointment_id", ""))
    elif func_name == "reschedule_appointment":
        return reschedule_appointment(
            args.get("appointment_id", ""),
            args.get("new_date", "tomorrow"),
            args.get("new_time", "")
        )
    return "Error: Unknown tool called."
