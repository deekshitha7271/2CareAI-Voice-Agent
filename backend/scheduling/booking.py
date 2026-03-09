import logging
from datetime import datetime
from typing import Optional, Dict, Any
from memory.session import acquire_booking_lock, release_booking_lock
from memory.database import get_db

logger = logging.getLogger("VoiceAI.Scheduling")

def process_booking_transaction(
    patient_name: str, 
    doctor_name: str, 
    date_str: str, 
    time_str: str,
    appt_dt: datetime,
    session_id: str
) -> str:
    """
    Handles the end-to-end booking of an appointment with strict
    collision detection and safety locks.
    """
    db = get_db()
    if db is None:
        return f"SUCCESS (offline mode): Appointment noted for {patient_name}."

    # 1. Acquire Redis Optimistic Lock
    # This prevents TWO different sessions from booking the same doctor/time
    # at the exact same millisecond.
    lock_key = f"{doctor_name}:{appt_dt.isoformat()}"
    if not acquire_booking_lock(doctor_name, appt_dt.isoformat(), session_id):
        return f"Sorry, someone else is currently trying to book {doctor_name} at {time_str}. Please choose another time."

    try:
        # 2. Final Pessimistic Check in MongoDB
        # Even with a lock, we check if the slot is ALREADY booked in the DB.
        existing = db.appointments.find_one({
            "doctor_name": {"$regex": doctor_name, "$options": "i"},
            "appointment_time": appt_dt,
            "status": "Booked"
        })
        if existing:
            return f"That slot is already confirmed for another patient. Let's find you another time."

        # 3. Create the Appointment Record
        doc = {
            "patient_name": patient_name,
            "doctor_name": doctor_name,
            "appointment_time": appt_dt,
            "date_str": date_str,
            "time_str": time_str,
            "status": "Booked",
            "booked_at": datetime.utcnow(),
            "channel": "voice_ai"
        }
        result = db.appointments.insert_one(doc)
        appt_id = str(result.inserted_id)

        # 4. Update the Patient's History
        db.patients.update_one(
            {"name": patient_name},
            {
                "$setOnInsert": {
                    "name": patient_name,
                    "registered_via": "voice_ai",
                    "created_at": datetime.utcnow(),
                },
                "$push": {
                    "appointments": {
                        "appointment_id": appt_id,
                        "doctor": doctor_name,
                        "date": date_str,
                        "time": time_str,
                        "status": "Booked"
                    }
                },
                "$set": {"last_booking": datetime.utcnow()}
            },
            upsert=True
        )

        logger.info(f"[Booking] Success: {patient_name} -> {doctor_name}")
        return f"Appointment confirmed with {doctor_name} on {date_str} at {time_str}. ID: {appt_id[:8].upper()}"

    except Exception as e:
        logger.error(f"[Booking] Transaction failed: {e}")
        return f"System error during booking: {str(e)}"
    finally:
        # 5. Release Lock
        release_booking_lock(doctor_name, appt_dt.isoformat(), session_id)


def cancel_appointment_transaction(appointment_id: str) -> str:
    """Marks an existing appointment as Cancelled."""
    db = get_db()
    if db is None:
        return "SUCCESS (offline mode): Appointment cancelled."

    try:
        from bson.objectid import ObjectId
        oid = ObjectId(appointment_id)
        
        # 1. Update Appointment Status
        appt = db.appointments.find_one_and_update(
            {"_id": oid},
            {"$set": {"status": "Cancelled", "updated_at": datetime.utcnow()}}
        )
        if not appt:
            return f"Error: Appointment {appointment_id} not found."

        # 2. Update Patient History
        db.patients.update_one(
            {"name": appt["patient_name"], "appointments.appointment_id": appointment_id},
            {"$set": {"appointments.$.status": "Cancelled"}}
        )

        logger.info(f"[Booking] Cancelled: {appointment_id}")
        return f"Appointment with {appt['doctor_name']} has been successfully cancelled."

    except Exception as e:
        logger.error(f"[Booking] Cancellation failed: {e}")
        return f"Failed to cancel appointment: {str(e)}"


def reschedule_appointment_transaction(
    appointment_id: str, 
    new_date_str: str, 
    new_time_str: str, 
    new_appt_dt: datetime,
    session_id: str
) -> str:
    """Moves an existing appointment to a new slot with full collision checks."""
    db = get_db()
    if db is None:
        return "SUCCESS (offline mode): Appointment rescheduled."

    try:
        from bson.objectid import ObjectId
        oid = ObjectId(appointment_id)
        
        # 1. Fetch existing appointment
        old_appt = db.appointments.find_one({"_id": oid})
        if not old_appt:
            return "Error: Could not find your existing appointment to reschedule."

        # 2. Run a standard booking transaction for the NEW slot
        # We reuse the booking logic to ensure the new slot is locked and free.
        new_slot_msg = process_booking_transaction(
            patient_name=old_appt["patient_name"],
            doctor_name=old_appt["doctor_name"],
            date_str=new_date_str,
            time_str=new_time_str,
            appt_dt=new_appt_dt,
            session_id=session_id
        )

        if "confirmed" in new_slot_msg.lower():
            # 3. If new slot is booked, cancel the OLD one
            cancel_appointment_transaction(appointment_id)
            return f"Great! Your appointment has been rescheduled to {new_date_str} at {new_time_str}."
        
        return new_slot_msg

    except Exception as e:
        logger.error(f"[Booking] Rescheduling failed: {e}")
        return f"Internal error during rescheduling: {str(e)}"
