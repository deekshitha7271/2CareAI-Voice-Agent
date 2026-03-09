import logging
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("VoiceAI.Database")

# ──────────────────────────────────────────────────────────────────────────────
# Lazy MongoDB connection — never blocks server startup
# ──────────────────────────────────────────────────────────────────────────────
_client = None
_db_instance = None
_connection_attempted = False

def _connect():
    global _client, _db_instance, _connection_attempted
    if _db_instance is not None:
        return _db_instance
    
    # If we already tried and failed, don't keep hanging the server
    if _connection_attempted and _db_instance is None:
        return None

    _connection_attempted = True
    mongodb_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    try:
        from pymongo import MongoClient
        # Short timeouts so we fail fast
        _client = MongoClient(
            mongodb_url,
            serverSelectionTimeoutMS=2000,   # reduced to 2s for better UI responsiveness
            connectTimeoutMS=2000,
            socketTimeoutMS=5000,
            tls=True,
            tlsAllowInvalidCertificates=False
        )
        _client.admin.command("ping")
        _db_instance = _client.clinical_agent
        logger.info("[DB] ✅ Connected to MongoDB Atlas successfully.")
        _ensure_indexes(_db_instance)
    except Exception as e:
        logger.warning(f"[DB] ⚠️ MongoDB unavailable. Switching to offline mode permanently for this session.")
        _db_instance = None

    return _db_instance


def _ensure_indexes(db):
    """Create performance indexes — called once after successful connection."""
    try:
        db.patients.create_index("phone_number", unique=True, sparse=True)
        db.appointments.create_index(
            [("doctor_name", 1), ("appointment_time", 1), ("status", 1)]
        )
        logger.info("[DB] Indexes ensured.")
    except Exception as e:
        logger.warning(f"[DB] Could not create indexes: {e}")


# Public API
def get_db():
    """Returns live DB instance, or None if MongoDB is unreachable."""
    return _connect()


# Module-level alias so `from memory.database import db` still works
class _LazyDB:
    """Proxy object — actual connection happens only on first attribute access."""
    def __getattr__(self, name):
        db = _connect()
        if db is None:
            raise RuntimeError("MongoDB is not available.")
        return getattr(db, name)


db = _LazyDB()
