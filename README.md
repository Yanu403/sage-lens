# 🔍 Mini AI Search Agent

A Telegram bot that searches the web in real-time and delivers AI-synthesized answers with source citations. Think Perplexity, but on Telegram.

## How It Works

```
User Query
    │
    ▼
Intent Router (Gemma) ─── classify: search / reason / search+reason
    │
    ├── search ──→ Tavily Search ──→ Content Extraction ──→ MiMo Synthesis
    │                                                            │
    └── reason ──────────────────────────────────────────→ MiMo Synthesis
                                                              │
                                                              ▼
                                                     Answer + Citations
                                                         (Telegram)
```

## Features

- **Real-time web search** via Tavily API — no stale databases
- **Smart intent routing** — knows when to search vs. just reason
- **Source citations** — every claim backed by a link
- **Response caching** — SQLite TTL cache for repeated queries
- **Rate limiting** — per-user sliding window
- **Multi-language** — responds in the user's language

## Models

| Role | Model | Provider |
|------|-------|----------|
| Intent Router | `gemma-4-26b-a4b-it` | Google Gemini API (free tier) |
| Synthesis | `mimo-v2.5-pro` | Xiaomi MiMo API |

## Setup

### 1. Clone & Install

```bash
git clone https://github.com/Yanu403/mini-search-agent.git
cd mini-search-agent
pip install -r requirements.txt
```

### 2. Get API Keys

- **Telegram Bot Token** — Talk to [@BotFather](https://t.me/BotFather)
- **Gemini API Key** — [Google AI Studio](https://aistudio.google.com/apikey) (free)
- **MiMo API Key** — [Xiaomi MiMo](https://mimo.xiaomi.com) 
- **Tavily API Key** — [tavily.com](https://tavily.com) (1000 free queries/month)

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your actual keys
```

### 4. Run

```bash
python bot.py
```

### 5. (Optional) Systemd Service

```bash
sudo cp mini-search-agent.service /etc/systemd/system/
sudo systemctl enable --now mini-search-agent
```

## Usage

Just send a message to the bot:

```
You: apa itu restaking di ethereum?

Bot: ⏳ Mencari...

Bot: 📋 Restaking adalah mekanisme di mana ETH yang sudah 
di-stake dapat digunakan kembali untuk mengamankan protokol 
lain melalui EigenLayer [1]. Ini memungkinkan validator 
mendapatkan reward tambahan tanpa harus menambah modal [2].

📎 Sumber:
1. EigenLayer: Restaking — eigenlayer.xyz
2. What is Restaking — coindesk.com
```

## Project Structure

```
mini-search-agent/
├── bot.py              # Telegram bot entry point
├── config.py           # Environment & constants
├── router.py           # Intent classification (Gemma)
├── search.py           # Tavily search + trafilatura
├── synthesizer.py      # MiMo synthesis + citations
├── cache.py            # SQLite async cache
├── formatter.py        # Telegram message formatting
├── rate_limiter.py     # Per-user rate limiting
├── requirements.txt
├── .env.example
└── .gitignore
```

## License

MIT
