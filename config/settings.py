"""Settings for the current FastAPI application.

The imported repository excluded its original config directory. Only settings
required by the active API are restored here; legacy ML tuning is not guessed.
"""
import os

from dotenv import load_dotenv

load_dotenv()

API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8000"))
API_PREFIX = "/api/v1"
PLATFORM_NAME = "AWI Enterprise Intelligence Platform"
PLATFORM_VERSION = "3.0.0"

# Cloud AI is opt-in. Both values must be supplied to use this optional mode.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "")
