import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()
if not SARVAM_API_KEY:
    # Try parent directory fallback
    parent_env = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(dotenv_path=parent_env)
    SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()

SARVAM_BASE_URL = "https://api.sarvam.ai"
SARVAM_TTS_ENDPOINT = f"{SARVAM_BASE_URL}/text-to-speech"
SARVAM_STT_ENDPOINT = f"{SARVAM_BASE_URL}/speech-to-text"
SARVAM_LLM_ENDPOINT = f"{SARVAM_BASE_URL}/v1/chat/completions"

DEFAULT_LLM_MODEL = "sarvam-105b-conversations"
DEFAULT_TTS_MODEL = "bulbul:v4-flash"
DEFAULT_STT_MODEL = "saaras:v4"
