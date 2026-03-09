"""
campaigns/worker.py
Celery background job queue for outbound campaign calls.
Uses Redis as both broker and result backend.
"""
import os
import logging
from datetime import datetime

logger = logging.getLogger("VoiceAI.Campaigns")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

try:
    from celery import Celery
    celery_app = Celery(
        "clinical_agent_campaigns",
        broker=REDIS_URL,
        backend=REDIS_URL,
    )
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Asia/Kolkata",
        enable_utc=True,
    )
    CELERY_AVAILABLE = True
except ImportError:
    celery_app = None
    CELERY_AVAILABLE = False
    logger.warning("[Campaigns] Celery not installed — running in offline mode.")


def _make_task(fn):
    """Decorator that conditionally registers as a Celery task."""
    if CELERY_AVAILABLE and celery_app:
        return celery_app.task(fn)
    # Fallback: plain callable when Celery unavailable
    return fn


@_make_task
def outbound_call_patient(patient_id: str, appointment_id: str):
    """
    Initiates an outbound voice reminder call for a patient.

    In production this would:
    1. Look up the patient's phone number from MongoDB
    2. Trigger a Twilio/Vonage API call that connects to our /ws/voice WebSocket
    3. The agent handles the conversation, logging confirmations / reschedules

    Returns a payload dict that Celery stores in Redis backend.
    """
    logger.info(f"[Campaigns] Outbound task started: patient={patient_id}, appt={appointment_id}")

    # Fetch patient details from MongoDB
    patient_info = {}
    appointment_info = {}
    try:
        from memory.database import get_db
        from bson.objectid import ObjectId
        db = get_db()
        if db:
            # Try fetching patient
            try:
                pid = ObjectId(str(patient_id)) if len(str(patient_id)) == 24 else None
                if pid:
                    patient_info = db.patients.find_one({"_id": pid}, {"_id": 0}) or {}
                else:
                    patient_info = db.patients.find_one({"name": patient_id}, {"_id": 0}) or {}
            except Exception:
                patient_info = db.patients.find_one({"name": patient_id}, {"_id": 0}) or {}

            # Try fetching appointment
            try:
                appt_oid = ObjectId(str(appointment_id)) if len(str(appointment_id)) == 24 else None
                if appt_oid:
                    appointment_info = db.appointments.find_one({"_id": appt_oid}, {"_id": 0}) or {}
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[Campaigns] DB lookup failed: {e}")

    patient_name = patient_info.get("name", f"patient_{patient_id}")
    doctor = appointment_info.get("doctor_name", "your doctor")
    date = appointment_info.get("date_str", "the scheduled date")
    time = appointment_info.get("time_str", "your scheduled time")

    # Outbound call payload — in production, sent to Twilio/Vonage API
    payload = {
        "to": patient_info.get("phone_number", f"+91_PATIENT_{patient_id}"),
        "from": "2Care_AI_Voice",
        "websocket_url": "wss://your-domain.com/ws/voice",
        "initial_message": (
            f"Hello {patient_name}! This is a reminder from 2Care AI. "
            f"You have an appointment with {doctor} on {date} at {time}. "
            f"Please say 'confirm' to keep it or 'reschedule' if you need to change."
        ),
        "session_id": f"outbound_{patient_id}_{appointment_id}",
        "triggered_at": datetime.utcnow().isoformat(),
    }

    logger.info(f"[Campaigns] Outbound call payload prepared for {patient_name}: {payload['initial_message'][:80]}")
    return {"status": "dialled", "payload": payload}


@_make_task
def send_appointment_reminder(patient_name: str, doctor_name: str, date: str, appt_time: str):
    """
    Simplified reminder task — sends a reminder for a known appointment.
    Used by the REST API when patient_id / appointment_id are not yet in DB.
    """
    logger.info(f"[Campaigns] Reminder task: {patient_name} → {doctor_name} on {date} at {appt_time}")
    payload = {
        "patient_name": patient_name,
        "doctor_name": doctor_name,
        "date": date,
        "time": appt_time,
        "message": (
            f"Hi {patient_name}, remember your appointment with {doctor_name} "
            f"is on {date} at {appt_time}. Reply CONFIRM or RESCHEDULE."
        ),
        "triggered_at": datetime.utcnow().isoformat(),
    }
    return {"status": "reminder_sent", "payload": payload}
