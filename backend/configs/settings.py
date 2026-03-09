import os
from dotenv import load_dotenv

load_dotenv()

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# External APIs
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "") # Fallback
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "")

# Databases
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")

# Logic
LATENCY_LOGGING = os.getenv("LATENCY_LOGGING", "True").lower() == "true"
