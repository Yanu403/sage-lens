<div align="center">

# 🔮 Sage Lens

### AI-Powered Search Agent for Telegram

*Ask anything. Get answers with real sources — not hallucinations.*

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white)](https://t.me/sagelens_bot)
[![Powered by MiMo](https://img.shields.io/badge/Powered%20by-MiMo%20v2.5-orange)](https://mimo.xiaomi.com)

</div>

---

Sage Lens is a lightweight Telegram bot that searches the web in real-time, reasons over the results, and delivers structured answers with source citations. Think **Perplexity**, but on Telegram.

## ✨ Features

- 🔍 **Real-time web search** — powered by Tavily, no stale databases
- 🧠 **Smart intent routing** — knows when to search vs. just reason (via Gemma)
- 📎 **Source citations** — every claim backed by a link you can verify
- ⚡ **Response caching** — SQLite TTL cache for repeated queries
- 🛡️ **Rate limiting** — per-user sliding window, configurable
- 🌐 **Multi-language** — responds in whatever language you ask in

## 🏗️ Architecture

```
                        ┌──────────────┐
                        │   Telegram    │
                        │     User      │
                        └──────┬───────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │     Sage Lens Bot     │
                    │  python-telegram-bot  │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │   Intent Router      │
                    │  Gemma 4 (26B)       │
                    │  via Gemini API      │
                    └──┬────────────────┬──┘
                       │                │
              ┌────────▼──────┐  ┌──────▼────────┐
              │   Web Search  │  │  Pure Reason  │
              │  Tavily API   │  │  (no search)  │
              └────────┬──────┘  └──────┬────────┘
                       │                │
              ┌────────▼──────┐         │
              │   Content     │         │
              │  Extraction   │         │
              │  trafilatura  │         │
              └────────┬──────┘         │
                       │                │
                    ┌──▼────────────────▼──┐
                    │   Synthesis Engine    │
                    │   MiMo v2.5 Pro      │
                    │   via Xiaomi API     │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │   📋 Answer + 📎     │
                    │   Sources to User    │
                    └──────────────────────┘
```

## 🤖 Models

| Role | Model | Provider | Cost |
|------|-------|----------|------|
| Intent Router | `gemma-4-26b-a4b-it` | Google Gemini API | Free tier |
| Synthesis | `mimo-v2.5-pro` | Xiaomi MiMo API | ~$0.02/1K queries |
| Search | Tavily | tavily.com | Free (1K/mo) |

## 🚀 Quick Start

### 1. Clone

```bash
git clone https://github.com/Yanu403/sage-lens.git
cd sage-lens
```

### 2. Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Get API Keys

| Key | Where | Cost |
|-----|-------|------|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) | Free |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) | Free |
| `MIMO_API_KEY` | [Xiaomi MiMo](https://mimo.xiaomi.com) | Free tier |
| `TAVILY_API_KEY` | [tavily.com](https://tavily.com) | Free (1K/mo) |

### 4. Configure

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 5. Run

```bash
# Direct
python bot.py

# Or as systemd service
sudo cp sage-lens.service /etc/systemd/system/
sudo systemctl enable --now sage-lens
```

## 💬 Usage

Just send a message to the bot:

```
You:  apa itu restaking di ethereum?

Bot:  ⏳ Mencari...

Bot:  📋 Restaking di Ethereum adalah proses menggunakan
      ETH yang sudah di-stake untuk mengamankan protokol
      lain melalui EigenLayer [1]. Ini memungkinkan
      validator mendapatkan reward tambahan [2].

      📎 Sumber:
      1. EigenLayer: Restaking — eigenlayer.xyz
      2. What is Restaking — coindesk.com
```

**Works with any language:**

```
You:  what is zero-knowledge proof?

Bot:  📋 A zero-knowledge proof (ZKP) is a cryptographic
      method where one party can prove to another that
      a statement is true, without revealing any info
      beyond the validity of the statement itself [1].
      ...
```

**Pure reasoning (no search needed):**

```
You:  explain the trolley problem in simple terms

Bot:  📋 The trolley problem is a thought experiment...
      (answers from knowledge, no web search)
```

## 📁 Project Structure

```
sage-lens/
├── bot.py              # Telegram bot — entry point
├── config.py           # Environment & constants
├── router.py           # Intent classification (Gemma)
├── search.py           # Tavily search + trafilatura
├── synthesizer.py      # MiMo synthesis + citations
├── cache.py            # SQLite async cache (TTL)
├── formatter.py        # Telegram message formatting
├── rate_limiter.py     # Per-user sliding window
├── requirements.txt    # Python dependencies
├── .env.example        # Config template
├── sage-lens.service   # Systemd unit file
└── LICENSE             # MIT
```

## ⚙️ Configuration

All config via `.env`:

```env
# Telegram
TELEGRAM_BOT_TOKEN=your_token

# LLM — Intent Router
GEMINI_API_KEY=your_key
GEMINI_MODEL=gemma-4-26b-a4b-it
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai

# LLM — Synthesis
MIMO_API_KEY=your_key
MIMO_MODEL=mimo-v2.5-pro
MIMO_BASE_URL=https://token-plan-sgp.xiaomimimo.com/v1

# Search
TAVILY_API_KEY=your_key

# Limits
RATE_LIMIT_PER_HOUR=20
CACHE_TTL_HOURS=6
MAX_SOURCES=5
MAX_CONTEXT_CHARS=8000
```

## 🧪 How It Works

1. **Intent Classification** — Gemma 4 classifies your query as `search`, `reason`, or `search_reason` and rewrites it for optimal web search
2. **Web Search** — Tavily fetches relevant pages; trafilatura extracts clean article text
3. **Synthesis** — MiMo v2.5 Pro reads the sources and generates a concise answer with inline citations `[1]`, `[2]`, etc.
4. **Caching** — Results are cached in SQLite with TTL (6h for search, 24h for reasoning)
5. **Rate Limiting** — In-memory sliding window (default: 20 queries/user/hour)

## 📊 Cost

| Component | Model | Est. per 1K queries |
|-----------|-------|---------------------|
| Intent routing | Gemma (Gemini API) | Free |
| Search | Tavily | Free (1K/mo) or $5 |
| Synthesis | MiMo v2.5 Pro | ~$0.02 |
| **Total** | | **~$0.02 – $5 / 1K queries** |

## 🛠️ Tech Stack

- **Python 3.11+** — async-first
- **python-telegram-bot 20.x** — Telegram Bot API
- **OpenAI SDK** — unified LLM client (Gemini + MiMo both OpenAI-compatible)
- **Tavily** — AI-optimized web search
- **trafilatura** — article content extraction
- **SQLite (aiosqlite)** — lightweight async cache
- **python-dotenv** — config management

## 📝 License

[MIT](LICENSE) — use it however you want.

## 🙏 Acknowledgments

- [Google Gemini](https://ai.google.dev/) — Gemma models for intent routing
- [Xiaomi MiMo](https://mimo.xiaomi.com) — MiMo v2.5 Pro for synthesis
- [Tavily](https://tavily.com) — web search infrastructure
- [trafilatura](https://trafilatura.readthedocs.io/) — content extraction

---

<div align="center">

**Built with ☕ and curiosity**

</div>
