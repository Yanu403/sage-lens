"""Sage Lens — AI Search Agent Telegram Bot (Entry Point)."""

from __future__ import annotations

import asyncio
import logging
import re
import sys

from openai import (
    AuthenticationError,
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    APIStatusError,
)
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ChatAction, ParseMode

import config
from cache import Cache
from rate_limiter import RateLimiter
from router import classify
from search import search, enrich_sources
from synthesizer import synthesize
from formatter import format_response

# ── Logging ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("sage-lens")

# ── Global instances ─────────────────────────────────────
cache = Cache()
rate_limiter = RateLimiter()

# ── Helpers ──────────────────────────────────────────────

_TRUNCATE_LEN = 50


def _t(s: str) -> str:
    """Truncate string for logging."""
    return s[:_TRUNCATE_LEN] + "..." if len(s) > _TRUNCATE_LEN else s


async def send_typing(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    try:
        await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        pass


async def typing_loop(
    ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, stop: asyncio.Event
) -> None:
    """Send typing indicator every 4 seconds until stop event is set."""
    while not stop.is_set():
        await send_typing(ctx, chat_id)
        try:
            await asyncio.sleep(4)
        except asyncio.CancelledError:
            break


def _strip_mention(text: str, bot_username: str | None) -> str:
    """Remove @botusername mention from the start or anywhere in the message."""
    if not bot_username:
        return text
    # Remove @username (case-insensitive)
    cleaned = re.sub(rf"@{re.escape(bot_username)}\b", "", text, flags=re.IGNORECASE)
    return cleaned.strip()


# ── Command Handlers ─────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    welcome = (
        "🔮 *Sage Lens*\n\n"
        "Kirim pertanyaan apapun, dan aku akan mencari di web "
        "lalu memberikan jawaban dengan sumber.\n\n"
        "*Contoh:*\n"
        "• Apa itu restaking di Ethereum?\n"
        "• Siapa pemenang UCL 2026?\n"
        "• Jelaskan konsep zero-knowledge proof\n\n"
        "Perintah:\n"
        "/start — Pesan ini\n"
        "/help — Bantuan"
    )
    await update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "🔮 *Cara Pakai:*\n\n"
        "Kirim pertanyaan atau topik yang ingin dicari. "
        "Bot akan:\n"
        "1. Menganalisis pertanyaanmu\n"
        "2. Mencari di internet secara real-time\n"
        "3. Merangkum jawaban dengan sitasi\n\n"
        "*Fitur:*\n"
        "• Pencarian real-time via Tavily\n"
        "• Jawaban dengan sumber terpercaya\n"
        "• Mendukung bahasa Indonesia & Inggris\n"
        "• Cache untuk respons lebih cepat\n\n"
        "*Batasan:*\n"
        f"• {config.RATE_LIMIT_PER_HOUR} query per jam per user\n"
        "• Stateless (tidak ada memori percakapan)"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


# ── Main Search Handler ──────────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Process a user query through the full search pipeline."""
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    raw_text = update.message.text.strip()

    if not raw_text:
        return

    # ── Group chat: only respond to @mentions or replies to bot ──
    is_group = update.effective_chat.type != "private"
    if is_group:
        bot_username = ctx.bot.username
        has_mention = f"@{bot_username}" in raw_text
        is_reply_to_bot = (
            update.message.reply_to_message
            and update.message.reply_to_message.from_user
            and update.message.reply_to_message.from_user.is_bot
        )
        if not has_mention and not is_reply_to_bot:
            return
        # Strip @mention from query text
        query = _strip_mention(raw_text, bot_username)
        if not query:
            await update.message.reply_text("Ketik pertanyaan setelah mention ya 🔮")
            return
    else:
        query = raw_text

    # ── Rate limit ───────────────────────────────────────
    allowed, remaining = await rate_limiter.check(user_id)
    if not allowed:
        await update.message.reply_text(
            f"⚠️ Kamu sudah mencapai batas {config.RATE_LIMIT_PER_HOUR} query per jam. "
            "Coba lagi nanti ya."
        )
        return

    # ── Check cache ──────────────────────────────────────
    cached = await cache.get(query)
    if cached:
        log.info("Cache hit: %s", _t(query))
        messages = format_response(cached["response"], cached.get("sources"))
        for msg in messages:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return

    # ── Start typing indicator ───────────────────────────
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(typing_loop(ctx, chat_id, stop_typing))

    try:
        # ── Step 1: Intent classification ────────────────
        classification = await classify(query)
        intent = classification["intent"]
        search_query = classification["search_query"] or query
        language = classification["language"]

        log.info("Query: %s → intent=%s search=%s", _t(query), intent, _t(search_query))

        # ── Step 2: Search (if needed) ───────────────────
        sources: list[dict] = []
        if intent in ("search", "search_reason"):
            sources = await search(search_query)
            if sources:
                sources = await enrich_sources(sources)
                log.info("Found %d sources", len(sources))

        # ── Step 3: Synthesis ────────────────────────────
        answer = await synthesize(
            query=query,
            sources=sources if sources else None,
            language=language,
        )

        # ── Step 4: Format & send ────────────────────────
        messages = format_response(answer, sources)
        for msg in messages:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

        # ── Step 5: Cache the result ─────────────────────
        await cache.put(query, answer, sources, intent)
        log.info("Cached: %s", _t(query))

    except AuthenticationError as e:
        log.error("API authentication failed: %s", e)
        await update.message.reply_text(
            "❌ Konfigurasi API bermasalah. Hubungi admin."
        )

    except RateLimitError as e:
        log.warning("API rate limit hit: %s", e)
        await update.message.reply_text(
            "⚠️ Server sedang sibuk. Coba lagi dalam beberapa menit."
        )

    except (APITimeoutError, APIConnectionError) as e:
        log.warning("API connection/timeout error: %s", e)
        await update.message.reply_text(
            "🌐 Koneksi ke server AI terputus. Coba lagi nanti."
        )

    except APIStatusError as e:
        log.error("API status error %s: %s", e.status_code, e)
        await update.message.reply_text(
            f"❌ Server AI mengembalikan error ({e.status_code}). Coba lagi nanti."
        )

    except Exception as e:
        log.error("Unexpected error for query '%s': %s", _t(query), e, exc_info=True)
        await update.message.reply_text(
            "❌ Terjadi error yang tidak terduga. Coba lagi nanti."
        )

    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


# ── Startup & Shutdown ───────────────────────────────────

async def _periodic_rate_cleanup(rl: RateLimiter) -> None:
    """Background task: prune expired rate-limit rows every hour."""
    while True:
        await asyncio.sleep(3600)
        try:
            removed = await rl.cleanup()
            if removed:
                log.info("Rate limiter cleanup: %d rows removed", removed)
        except Exception as e:
            log.debug("Rate limiter cleanup error: %s", e)


async def post_init(app: Application) -> None:
    await cache.init()
    await rate_limiter.init()
    asyncio.create_task(_periodic_rate_cleanup(rate_limiter))
    log.info("Cache + Rate limiter initialized")


async def post_shutdown(app: Application) -> None:
    await cache.close()
    await rate_limiter.close()
    log.info("Cache + Rate limiter closed")


# ── Main ─────────────────────────────────────────────────

def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    log.info("Starting Sage Lens...")
    log.info("Gemma: %s @ %s", config.GEMINI_MODEL, config.GEMINI_BASE_URL)
    log.info("MiMo:  %s @ %s", config.MIMO_MODEL, config.MIMO_BASE_URL)
    log.info("Mode:  %s", config.BOT_MODE)

    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if config.BOT_MODE == "webhook":
        log.info("Webhook mode: %s", config.WEBHOOK_URL)
        app.run_webhook(
            listen="0.0.0.0",
            port=config.WEBHOOK_PORT,
            url_path=config.TELEGRAM_BOT_TOKEN,
            webhook_url=f"{config.WEBHOOK_URL}/{config.TELEGRAM_BOT_TOKEN}",
            drop_pending_updates=True,
        )
    else:
        log.info("Polling mode")
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


if __name__ == "__main__":
    main()
