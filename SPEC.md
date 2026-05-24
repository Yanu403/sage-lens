# Mini AI Search Agent — Telegram Bot Spec

## Goal

Build an **independent** Telegram bot that answers user queries with real-time web search + LLM synthesis, delivering structured answers with source citations. Standalone project, no dependency on Hermes Agent — ready to push to GitHub.

## Context

- Target: fast responses (< 15s), good accuracy, low cost
- Must be fully self-contained — own config, own dependencies, own .env
- Will be published as a public GitHub repo

## Model Strategy

| Role | Model | Provider | Why |
|------|-------|----------|-----|
| Intent Router | `gemma-3-27b-it` | Google Gemini API | Free tier, fast, good at classification |
| Synthesis | `mimo-v2.5-pro` | Xiaomi MiMo API | Strong reasoning, OpenAI-compatible API |

**Why this combo:**
- Gemma via Gemini API: free tier 15 RPM / 1M tokens/day — more than enough for intent routing
- MiMo v2.5 Pro: excellent reasoning, 128K context, OpenAI-compatible endpoint
- Both accessed via standard `openai` Python library (Gemini has OpenAI-compatible endpoint)

## Search Provider

**Tavily** — purpose-built for AI search. Returns clean snippets + extracted content. Much better than DuckDuckGo scraping.

- Free tier: 1000 queries/month
- Paid: $0.005/query
- Returns: title, url, content snippet, relevance score

---

## In Scope

1. Telegram bot interface (1:1 DM + group mention)
2. Intent classification via Gemma (search / reason / search+reason)
3. Tavily search + content extraction (trafilatura)
4. MiMo synthesis with inline citations
5. Response caching (SQLite, TTL-based)
6. Rate limiting per user
7. Systemd service deployment
8. GitHub-ready: README, LICENSE, .env.example, .gitignore

## Out of Scope

- Multi-turn conversation memory (v1 is stateless per-query)
- Image/video search
- PDF parsing
- Premium tiers / auth
- Admin dashboard
- Voice input

---

## Architecture

```
User (Telegram)
     │
     ▼
┌─────────────────────┐
│  Telegram Bot        │  python-telegram-bot 20.x (async)
│  (polling mode)      │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Intent Router       │  gemma-3-27b-it (Google Gemini API)
│  → search | reason   │  returns: {intent, search_query, language}
│    | search+reason   │
└────────┬────────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌────────────┐
│ Tavily │ │ Reasoning  │
│ Search │ │ Only       │
└───┬────┘ └─────┬──────┘
    │            │
    ▼            │
┌─────────┐      │
│ Fetch   │      │
│trafiltra│      │
└───┬─────┘      │
    │            │
    ▼            ▼
┌─────────────────────┐
│  Synthesis LLM      │  mimo-v2.5-pro (Xiaomi MiMo API)
│  context + query     │  OpenAI-compatible endpoint
│  → answer + citations│
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Response Formatter  │  Telegram markdown
│  answer + 📎 sources │
└─────────────────────┘
```

---

## Components Detail

### 1. Config

All config via `.env` file, loaded with `python-dotenv`:

```env
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token

# LLM — Intent Router (Gemma via Gemini API)
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemma-3-27b-it
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai

# LLM — Synthesis (MiMo)
MIMO_API_KEY=your_mimo_key
MIMO_MODEL=mimo-v2.5-pro
MIMO_BASE_URL=https://token-plan-sgp.xiaomimimo.com/v1

# Search
TAVILY_API_KEY=your_tavily_key

# Limits
RATE_LIMIT_PER_HOUR=20
CACHE_TTL_HOURS=6
MAX_SOURCES=5
MAX_CONTEXT_CHARS=8000
```

### 2. Telegram Bot

**Framework:** python-telegram-bot 20.x (async, polling mode)

**Handlers:**
- `/start` — welcome + usage
- `/help` — capabilities
- Any text → search pipeline
- Group: only respond when bot is @mentioned

**UX:**
```
User: apa itu restaking di ethereum?
Bot:  ⏳ Mencari...
      (typing indicator setiap 4 detik)
Bot:  📋 Restaking adalah...
      
      📎 Sumber:
      1. Ethereum Restaking Guide — ethereum.org
      2. What is Restaking — coindesk.com
```

### 3. Intent Router (Gemma)

```python
# Via openai library pointing to Gemini's OpenAI-compatible endpoint
client = OpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_BASE_URL)

response = client.chat.completions.create(
    model="gemma-3-27b-it",
    messages=[{"role": "user", "content": intent_prompt}],
    response_format={"type": "json_object"},
    temperature=0.1
)
# Returns: {"intent": "search", "search_query": "ethereum restaking explained", "language": "id"}
```

**Intent categories:**
- `search` — needs real-time web info
- `reason` — pure reasoning (math, logic, general knowledge)
- `search_reason` — needs web info + analysis

### 4. Tavily Search

```python
# Tavily Python SDK
from tavily import TavilyClient

client = TavilyClient(api_key=TAVILY_API_KEY)
results = client.search(
    query=search_query,
    max_results=5,
    include_raw_content=True,  # full page content
    search_depth="advanced"
)
# Returns: {results: [{title, url, content, raw_content, score}]}
```

### 5. Content Extraction (trafilatura)

Fallback when Tavily `raw_content` is insufficient:

```python
import trafilatura

downloaded = trafilatura.fetch_url(url)
text = trafilatura.extract(downloaded)  # clean article text
```

**Context budget:** 8000 chars total, split evenly across sources.

### 6. Synthesis (MiMo)

```python
# Via openai library pointing to MiMo endpoint
client = OpenAI(api_key=MIMO_API_KEY, base_url=MIMO_BASE_URL)

response = client.chat.completions.create(
    model="mimo-v2.5-pro",
    messages=[
        {"role": "system", "content": SYNTHESIS_PROMPT},
        {"role": "user", "content": f"Question: {query}\n\nSources:\n{formatted_sources}"}
    ],
    temperature=0.3
)
```

**Note:** MiMo v2.5 Pro has thinking mode. Set `reasoning_effort` or use appropriate params to control it. If thinking mode causes 400 errors (reasoning_content passthrough), disable it via extra_body params.

### 7. Cache (SQLite)

```sql
CREATE TABLE IF NOT EXISTS cache (
    query_hash TEXT PRIMARY KEY,
    query_text TEXT,
    response TEXT,
    sources_json TEXT,
    intent TEXT,
    created_at REAL,
    hit_count INTEGER DEFAULT 0,
    ttl_hours INTEGER DEFAULT 6
);
```

- Normalize query → SHA256 hash → lookup
- TTL: search=6h, reason=24h, search_reason=4h
- LRU eviction at 10K entries

### 8. Rate Limiting

In-memory sliding window per user_id:

```python
_rate_windows: dict[int, list[float]] = {}

def check_rate_limit(user_id: int, limit: int = 20, window: int = 3600) -> bool:
    now = time.time()
    if user_id not in _rate_windows:
        _rate_windows[user_id] = []
    _rate_windows[user_id] = [t for t in _rate_windows[user_id] if now - t < window]
    if len(_rate_windows[user_id]) >= limit:
        return False
    _rate_windows[user_id].append(now)
    return True
```

---

## Project Structure

```
mini-search-agent/
├── README.md
├── LICENSE
├── .gitignore
├── .env.example          # Template with placeholder values
├── requirements.txt
├── config.py             # Load .env, constants
├── bot.py                # Entry point — Telegram handlers
├── router.py             # Intent classification (Gemma)
├── search.py             # Tavily search + trafilatura extraction
├── synthesizer.py        # MiMo synthesis with citations
├── cache.py              # SQLite cache layer
├── formatter.py          # Telegram message formatting
├── rate_limiter.py       # Per-user rate limiting
└── data/                 # Runtime data (gitignored)
    └── cache.db
```

---

## Deployment

```bash
# Install
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with actual keys

# Run
python bot.py

# Or via systemd
sudo cp mini-search-agent.service /etc/systemd/system/
sudo systemctl enable --now mini-search-agent
```

---

## Dependencies

```
python-telegram-bot>=20.8
httpx>=0.28
openai>=1.0
tavily-python>=0.5
trafilatura>=1.12
python-dotenv>=1.0
aiosqlite>=0.20
```

---

## Cost Estimate (per 1000 queries)

| Component | Model | Est. tokens/query | Cost |
|-----------|-------|-------------------|------|
| Intent routing | gemma-3-27b-it | ~300 | Free (Gemini free tier) |
| Search | Tavily | — | $5.00 (paid) / Free (1K/month) |
| Synthesis | mimo-v2.5-pro | ~8000 | ~$0.02 (MiMo pricing) |
| **Total** | | | **~$5/1000 queries** or **free at low volume** |

---

## Risks

1. **Gemini free tier limits** — 15 RPM may bottleneck at scale. Fallback: use 9routers for Gemma routing.
2. **MiMo thinking mode** — may need `reasoning_effort` param to avoid 400 errors. Test first.
3. **Tavily free tier** — 1000/month may not be enough. Monitor usage.
4. **trafilatura blocked** — some sites return empty. Fallback to Tavily snippet only.
5. **Telegram group floods** — bot may be too responsive. Add cooldown in groups.
