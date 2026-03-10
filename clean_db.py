import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))
from memory.database import get_db

db = get_db()
if db is not None:
    appts = list(db.appointments.find({"status": "Booked"}))
    seen = set()
    deleted = 0
    for a in appts:
        key = (a.get('patient_name'), a.get('doctor_name'))
        if key in seen:
            db.appointments.delete_one({"_id": a['_id']})
            deleted += 1
            print(f"Deleted duplicate appointment: {key}")
        else:
            seen.add(key)
    print(f"Cleanup done, removed {deleted} duplicates.")
else:
    print("Database connection failed.")
