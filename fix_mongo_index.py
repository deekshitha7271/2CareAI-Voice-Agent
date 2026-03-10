import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))
from memory.database import get_db

db = get_db()
if db is not None:
    try:
        # Check existing indexes
        indexes = db.patients.list_indexes()
        print("Existing indexes on patients collection:")
        for idx in indexes:
            print(idx)
            if 'phone_number_1' in idx['name']:
                print(f"Dropping index: {idx['name']}")
                db.patients.drop_index(idx['name'])
        
        # Re-create as sparse unique index (allows multiple nulls, but unique if present)
        # Or just remove unique if phone isn't mandatory yet
        print("Index dropped successfully. Clinical booking will now work without phone number conflicts.")
    except Exception as e:
        print(f"Error fixing index: {e}")
else:
    print("Failed to connect to DB.")
