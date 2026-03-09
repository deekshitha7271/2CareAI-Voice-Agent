import pytest
from datetime import datetime
from scheduling.booking import process_booking_transaction

def test_resolve_date_mock():
    # Simple logic check for tool helpers
    from agents.tools import _resolve_date
    assert _resolve_date("today") == str(datetime.now().date())

def test_booking_transaction_offline():
    # Test simulation mode
    res = process_booking_transaction(
        "Unit Test", "Dr. Logic", "2026-01-01", "10:00 AM", 
        datetime(2026, 1, 1, 10, 0), "test_session"
    )
    # If DB is None, it returns SUCCESS (offline mode)
    assert "Appointment confirmed" in res or "SUCCESS" in res
