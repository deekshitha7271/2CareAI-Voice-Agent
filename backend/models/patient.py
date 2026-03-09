from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class PatientAppointment(BaseModel):
    appointment_id: str
    doctor: str
    date: str
    time: str
    status: str = "Booked"

class Patient(BaseModel):
    name: str
    phone_number: Optional[str] = None
    registered_via: str = "voice_ai"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_booking: Optional[datetime] = None
    appointments: List[PatientAppointment] = []
