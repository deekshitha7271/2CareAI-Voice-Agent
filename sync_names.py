import sys
import os

# Add backend to path so we can import database
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from memory.database import get_db

db = get_db()
if db is not None:
    # Update appointments
    res = db.appointments.update_many(
        {'doctor_name': {'$regex': 'miku', '$options': 'i'}}, 
        {'$set': {'doctor_name': 'Dr. Medha'}}
    )
    print(f"Updated {res.modified_count} appointments from Miku to Medha.")
    
    # Update doctors collection just in case
    res2 = db.doctors.update_many(
        {'name': {'$regex': 'miku', '$options': 'i'}},
        {'$set': {'name': 'Dr. Medha'}}
    )
    print(f"Updated {res2.modified_count} records in doctors collection.")
else:
    print("Failed to connect to DB.")
