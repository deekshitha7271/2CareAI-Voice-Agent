"""
services/language_service.py
Lightweight language detection for English, Hindi, and Tamil.
Uses Unicode character-range heuristics — no external API needed,
which keeps latency near zero.
"""
import re
import logging

logger = logging.getLogger("VoiceAI.LangService")

# Unicode ranges
_DEVANAGARI = re.compile(r'[\u0900-\u097F]')   # Hindi / Devanagari script
_TAMIL      = re.compile(r'[\u0B80-\u0BFF]')   # Tamil script


# Common Romanized keywords for Hinglish/Tanglish detection
_HINDI_ROMAN = {"aap", "madad", "madhav", "kar", "hain", "kya", "namaste", "sakte", "hai", "mujhe", "kariye", "book", "appointment", "doctor", "saath"}
_TAMIL_ROMAN = {"enna", "irukku", "vaanga", "ponga", "pannunga", "doctor", "vanakkam", "yenna"}

def detect_language(text: str) -> str:
    """
    Detect the script / language of *text*.
    """
    if not text:
        return "en"

    # 1. Check Unicode script (High confidence)
    devanagari_count = len(_DEVANAGARI.findall(text))
    tamil_count      = len(_TAMIL.findall(text))
    total_chars      = max(len(text.replace(" ", "")), 1)

    if devanagari_count / total_chars >= 0.15:
        return "hi"
    if tamil_count / total_chars >= 0.15:
        return "ta"

    # 2. Check Romanized Keywords (Medium confidence)
    words = set(text.lower().split())
    if words & _HINDI_ROMAN:
        # If there's overlap with Hindi romanized words, and it's not predominantly Tamil
        return "hi"
    if words & _TAMIL_ROMAN:
        return "ta"

    return "en"


# Language display labels for the UI
LANG_LABELS = {
    "en": "EN 🇺🇸",
    "hi": "HI 🇮🇳",
    "ta": "TA 🇮🇳",
}
