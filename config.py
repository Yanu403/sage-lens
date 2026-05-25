"""Configuration — loads .env and defines constants."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)

# ── Telegram ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ── Bot Mode ─────────────────────────────────────────────
# "polling" (default) or "webhook"
BOT_MODE = os.getenv("BOT_MODE", "polling")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # e.g. https://sagelens.example.com
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8443"))

# ── LLM — Intent Router (Gemma via Gemini API) ──────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemma-4-26b-a4b-it")
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai",
)

# ── LLM — Synthesis (provider-agnostic, OpenAI-compatible) ──
# Works with: MiMo, GPT, DeepSeek, Kimi, Claude (via OpenRouter), etc.
SYNTHESIS_API_KEY = os.getenv("SYNTHESIS_API_KEY", os.getenv("MIMO_API_KEY", ""))
SYNTHESIS_MODEL = os.getenv("SYNTHESIS_MODEL", os.getenv("MIMO_MODEL", "mimo-v2.5-pro"))
SYNTHESIS_BASE_URL = os.getenv(
    "SYNTHESIS_BASE_URL",
    os.getenv("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
)

# ── Conversation Memory ─────────────────────────────────
CONVERSATION_MAX_HISTORY = int(os.getenv("CONVERSATION_MAX_HISTORY", "10"))
CONVERSATION_TTL_SECONDS = int(os.getenv("CONVERSATION_TTL_SECONDS", "600"))

# ── Search ───────────────────────────────────────────────
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# ── Limits ───────────────────────────────────────────────
RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", "20"))
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "6"))
MAX_SOURCES = int(os.getenv("MAX_SOURCES", "5"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "8000"))

# ── Derived ──────────────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_DB_PATH = DATA_DIR / "cache.db"

# ── Intent TTL map (hours) ───────────────────────────────
INTENT_TTL = {
    "search": 6,
    "search_reason": 4,
    "reason": 24,
}
