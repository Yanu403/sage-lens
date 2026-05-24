"""Mini AI Search Agent — Telegram Bot Entry Point."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

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
from rate_limiter import check_rate_limit
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
log = logging.getLogger("mini-search")

# ── Global cache instance ────────────────────────────────
cache = Cache()


# ── Helpers ──────────────────────────────────────────────

async def send_typing(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Send typing indicator."""
    try:
        await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        pass


async def typing_loop(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, stop: asyncio.Event) -> None:
    """Send typing indicator every 4 seconds until stop event is set."""
    while not stop.is_set():
        await send_typing(ctx, chat_id)
        try:
            await asyncio.sleep(4)
        except asyncio.CancelledError:
            break


# ── Command Handlers ─────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    welcome = (
        "🔍 *Mini AI Search Agent*\n\n"
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
    """Handle /help command."""
    help_text = (
        "🔍 *Cara Pakai:*\n\n"
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

    # In groups, only respond to @mentions or replies to bot
    if update.effective_chat.type != "private":
        bot_username = ctx.bot.username
        text = update.message.text
        if f"@{bot_username}" not in text and not (
            update.message.reply_to_message
            and update.message.reply_to_message.from_user
            and update.message.reply_to_message.from_user.is_bot
        ):
            return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    query = update.message.text.strip()

    if not query:
        return

    # ── Rate limit ───────────────────────────────────────
    allowed, remaining = check_rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(
            "⚠️ Kamu sudah mencapai batas {limit} query per jam. "
            "Coba lagi nanti ya.".format(limit=config.RATE_LIMIT_PER_HOUR)
        )
        return

    # ── Check cache ──────────────────────────────────────
    cached = await cache.get(query)
    if cached:
        log.info("Cache hit for query: %s", query[:50])
        messages = format_response(cached["response"], cached["sources"])
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

        log.info("Query: %s → intent=%s, search=%s", query[:50], intent, search_query[:50])

        # ── Step 2: Search (if needed) ───────────────────
        sources = []
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
        messages = format_response(answer, sources if sources else None)
        for msg in messages:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

        # ── Step 5: Cache the result ─────────────────────
        await cache.put(query, answer, sources, intent)
        log.info("Cached response for: %s", query[:50])

    except Exception as e:
        log.error("Pipeline error for query '%s': %s", query[:50], e, exc_info=True)
        await update.message.reply_text(
            "❌ Terjadi error saat memproses pertanyaanmu. Coba lagi nanti."
        )

    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


# ── Startup & Shutdown ───────────────────────────────────

async def post_init(app: Application) -> None:
    """Initialize cache after bot starts."""
    await cache.init()
    log.info("Cache initialized at %s", config.CACHE_DB_PATH)


async def post_shutdown(app: Application) -> None:
    """Close cache on shutdown."""
    await cache.close()
    log.info("Cache closed")


# ── Main ─────────────────────────────────────────────────

def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    log.info("Starting Mini AI Search Agent...")
    log.info("Gemma model: %s @ %s", config.GEMINI_MODEL, config.GEMINI_BASE_URL)
    log.info("MiMo model: %s @ %s", config.MIMO_MODEL, config.MIMO_BASE_URL)

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

    # Run with polling
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
