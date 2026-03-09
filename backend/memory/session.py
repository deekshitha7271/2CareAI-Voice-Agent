import os
import redis
import json
from datetime import datetime, timedelta

# Fast Session Memory & Distributed Locking
# Using local Redis by default for testing
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
except Exception as e:
    print(f"Failed to connect to Redis: {e}")
    redis_client = None

def get_session_history(session_id: str):
    """Fetch short-term conversation context."""
    if not redis_client:
        return []
    
    data = redis_client.lrange(f"session:{session_id}:history", 0, -1)
    return [json.loads(item) for item in data]

def add_session_message(session_id: str, message_dict: dict):
    """Add full message object to short-term memory (includes tool_calls/ids)."""
    if not redis_client:
        return
    
    msg = json.dumps(message_dict)
    # Store in list
    redis_client.rpush(f"session:{session_id}:history", msg)
    # Give session a 30 minute TTL (Time To Live)
    redis_client.expire(f"session:{session_id}:history", 1800)

def acquire_booking_lock(doctor_id: str, slot_datetime: str, session_id: str) -> bool:
    """
    Optimistic Locking for double-booking prevention.
    Returns True if lock acquired, False if slot is already being booked by someone else.
    """
    if not redis_client:
        return True # Fallback if redis isn't running
        
    lock_key = f"lock:slot:{doctor_id}:{slot_datetime}"
    
    # Try to set the key. NX=True means only set if it doesn't exist.
    # EX=60 means lock expires in 60 seconds (giving patient time to confirm).
    acquired = redis_client.set(lock_key, session_id, nx=True, ex=60)
    return acquired

def release_booking_lock(doctor_id: str, slot_datetime: str, session_id: str):
    """Release lock after booking or if patient changes mind."""
    if not redis_client:
        return
        
    lock_key = f"lock:slot:{doctor_id}:{slot_datetime}"
    current_holder = redis_client.get(lock_key)
    
    # Only release if we own the lock
    if current_holder == session_id:
        redis_client.delete(lock_key)
