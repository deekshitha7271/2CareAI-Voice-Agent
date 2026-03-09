"""
models/doctor.py
Pydantic schemas for Doctor data.
"""
from pydantic import BaseModel
from typing import List


# ── Source of truth for the doctor roster ──────────────────────────────────
# Edit ONLY here — tools.py and the system prompt read from this list.
DOCTORS: List[dict] = [
    {"name": "Dr. Dicky",  "specialization": "General Physician", "clinic_hours": "09:00-17:00"},
    {"name": "Dr. Miku",   "specialization": "Cardiologist",       "clinic_hours": "10:00-18:00"},
    {"name": "Dr. Kyathi", "specialization": "Dermatologist",      "clinic_hours": "09:00-15:00"},
    {"name": "Dr. Nasa",   "specialization": "Gynecologist",       "clinic_hours": "10:00-17:00"},
    {"name": "Dr. Priya",  "specialization": "Orthopedic",         "clinic_hours": "09:00-16:00"},
]

DOCTOR_NAMES = [d["name"] for d in DOCTORS]


class DoctorSchema(BaseModel):
    name: str
    specialization: str
    clinic_hours: str
