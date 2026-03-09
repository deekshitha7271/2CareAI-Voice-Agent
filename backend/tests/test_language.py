import pytest
from services.language_service import detect_language

def test_detect_english():
    assert detect_language("Hello, how are you?") == "en"

def test_detect_hindi():
    # "Namaste" in Devanagari
    assert detect_language("नमस्ते, आप कैसे हैं?") == "hi"

def test_detect_tamil():
    # "Vanakkam" in Tamil
    assert detect_language("வணக்கம், நீங்கள் எப்படி இருக்கிறீர்கள்?") == "ta"

def test_mixed_language_preference():
    # Mostly English with one Hindi word should still be EN
    assert detect_language("Hello, how are you? namaste") == "en"
