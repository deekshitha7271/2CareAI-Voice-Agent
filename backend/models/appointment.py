from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class Appointment(BaseModel):
    patient_name: str
    doctor_name: str
    appointment_time: datetime
    date_str: str
    time_str: str
    status: str = "Booked"
    booked_at: datetime = Field(default_factory=datetime.utcnow)
    channel: str = "voice_ai"
