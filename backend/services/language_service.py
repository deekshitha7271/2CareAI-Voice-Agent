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


def detect_language(text: str) -> str:
    """
    Detect the script / language of *text*.

    Returns:
        "hi"  — Hindi  (Devanagari characters detected)
        "ta"  — Tamil  (Tamil characters detected)
        "en"  — English (default / fallback)

    The detection counts characters rather than just checking for presence,
    so a sentence like "Call me kal" (mostly English) still returns "en".
    """
    if not text:
        return "en"

    devanagari_count = len(_DEVANAGARI.findall(text))
    tamil_count      = len(_TAMIL.findall(text))
    total_chars      = max(len(text.replace(" ", "")), 1)

    # Require at least 15 % of characters to be script-specific to classify
    if devanagari_count / total_chars >= 0.15:
        logger.debug(f"[Lang] Detected Hindi (Devanagari ratio={devanagari_count/total_chars:.2f})")
        return "hi"
    if tamil_count / total_chars >= 0.15:
        logger.debug(f"[Lang] Detected Tamil (Tamil ratio={tamil_count/total_chars:.2f})")
        return "ta"

    return "en"


# Language display labels for the UI
LANG_LABELS = {
    "en": "EN 🇺🇸",
    "hi": "HI 🇮🇳",
    "ta": "TA 🇮🇳",
}
