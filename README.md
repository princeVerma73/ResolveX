# ⚡ ResolveX — Autonomous AI Customer Support Agent

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-FF6B35?style=flat-square)](https://github.com/langchain-ai/langgraph)
[![Qdrant](https://img.shields.io/badge/Qdrant-Vector%20DB-DC2626?style=flat-square)](https://qdrant.tech/)
[![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?style=flat-square&logo=supabase&logoColor=white)](https://supabase.com)
[![Redis](https://img.shields.io/badge/Redis-Cache-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io/)
[![Tests](https://img.shields.io/badge/Tests-229%20Passed%20%7C%20100%25-22C55E?style=flat-square)](./tests)
[![License](https://img.shields.io/badge/License-MIT-6366F1?style=flat-square)](LICENSE)
[![Netlify](https://img.shields.io/badge/Netlify-Live%20Demo-00C7B7?style=flat-square&logo=netlify&logoColor=white)](https://resolvex-ai.netlify.app/)
[![Render](https://img.shields.io/badge/Render-API%20Live-46E3B7?style=flat-square&logo=render&logoColor=white)](https://resolvex-bd8o.onrender.com)

> 🚀 **Live Demo:** [https://resolvex-ai.netlify.app/](https://resolvex-ai.netlify.app/)
> 🔗 **Backend API:** [https://resolvex-bd8o.onrender.com](https://resolvex-bd8o.onrender.com) | **Swagger UI:** [/docs](https://resolvex-bd8o.onrender.com/docs)

---

## 📌 Overview

**ResolveX** is a production-grade, **autonomous AI customer support agent** built to resolve high-volume e-commerce inquiries with zero human touch — and intelligently escalate the ones that require it.

It combines a **LangGraph multi-agent orchestrator** with a **hybrid RAG knowledge engine** (Qdrant + FlashRank neural reranking), **transactional database lookups** (Supabase PostgreSQL), and a **real-time streaming frontend** — all deployed end-to-end on modern cloud infrastructure.

**What ResolveX handles autonomously:**
- 📦 **Track & look up orders** by ID across a live PostgreSQL database
- 📋 **Answer policy questions** grounded in indexed company documents (refunds, shipping, cancellations)
- ⚙️ **Execute order mutations** (cancellations, modifications) with guardrails
- 🔧 **Run multi-turn technical diagnostics** workflows
- 🚨 **Escalate unresolvable cases** to human agents with auto-generated ticket references (`TCK-XXXX`)

---

## 🏗️ System Architecture

```mermaid
flowchart TD
    subgraph Client ["Web Client (Vanilla JS · Tailwind CSS)"]
        UI[Chat Canvas and Theme Engine]
        WS_CLIENT[WebSocket Streaming Client]
        TELEMETRY[Real-Time Telemetry Dashboard]
        STORAGE[LocalStorage Session Isolation]
    end

    subgraph API ["FastAPI Application Gateway (Render)"]
        WS_ROUTE["/ws/chat/{session_id}"]
        REST_ROUTE["/api/chat · /health · /api/visitors"]
        CORS[CORS Middleware and Exception Handlers]
    end

    subgraph LangGraph ["LangGraph Multi-Agent Engine"]
        ROUTER[Supervisor and Intent Router]
        POLICY_NODE[Policy RAG Agent]
        ORDER_NODE[Database Lookup Agent]
        ACTION_NODE[Action Execution Agent]
        TECH_NODE[Technical Diagnostics Agent]
        ESCALATE_NODE[Human Escalation Node]
    end

    subgraph RAG ["Hybrid RAG Pipeline"]
        QDRANT[(Qdrant Vector DB Cloud)]
        FLASHRANK[FlashRank Neural Reranker]
        RRF[Reciprocal Rank Fusion]
    end

    subgraph Storage ["Persistence Layer"]
        SUPABASE[(Supabase PostgreSQL)]
        REDIS[(Redis Cache Layer)]
        JSON_STORE[(Orders and Visitor Counter)]
    end

    UI <--> WS_CLIENT
    WS_CLIENT <-->|WebSocket Frames| WS_ROUTE
    UI <-->|REST Fallback| REST_ROUTE

    WS_ROUTE --> CORS --> ROUTER
    REST_ROUTE --> CORS

    ROUTER -->|POLICY_INQUIRY| POLICY_NODE
    ROUTER -->|DATABASE_LOOKUP| ORDER_NODE
    ROUTER -->|ACTION_EXECUTION| ACTION_NODE
    ROUTER -->|TECHNICAL_SUPPORT| TECH_NODE
    ROUTER -->|GENERAL_ESCALATION| ESCALATE_NODE

    POLICY_NODE <--> QDRANT
    POLICY_NODE <--> FLASHRANK
    FLASHRANK <--> RRF
    ORDER_NODE <--> SUPABASE
    ORDER_NODE <--> JSON_STORE
    ACTION_NODE <--> JSON_STORE
    ESCALATE_NODE --> SUPABASE
    REST_ROUTE <--> REDIS
    WS_ROUTE <--> REDIS
```

> 📝 *Optionally replace the diagram above with a PNG:*
> `![Architecture Diagram](./docs/screenshots/architecture_diagram.png)`

---

## ✨ Key Features

### 🧠 Multi-Agent Orchestration (LangGraph)

A **supervisor-router pattern** classifies every incoming query into one of five intent domains and dispatches it to the right specialist agent node — with shared conversational state across the entire graph.

| Intent | Agent | Capability |
|:---|:---|:---|
| `POLICY_INQUIRY` | Policy RAG Agent | Grounded Q&A with citation attribution |
| `DATABASE_LOOKUP` | Order Lookup Agent | Live order + payment queries from Supabase |
| `ACTION_EXECUTION` | Action Agent | Order cancellations with mutation guardrails |
| `TECHNICAL_SUPPORT` | Diagnostics Agent | Multi-turn troubleshooting workflows |
| `GENERAL_ESCALATION` | Escalation Node | Auto-ticket creation with `TCK-XXXX` codes |

---

### 📚 Hybrid RAG Knowledge Engine

- **Dense Vector Search** via **Qdrant** (hosted vector database) with semantic embeddings
- **Neural Cross-Encoder Reranking** via **FlashRank** to maximize answer groundedness
- **Reciprocal Rank Fusion (RRF)** for combining multiple retrieval signals
- **Strict Groundedness Threshold** (≥ 0.75) — queries below threshold cleanly escalate rather than hallucinate
- **Citation Attribution** — every RAG response includes `chunk_id` source references

---

### 📊 Real-Time Telemetry Dashboard

An in-browser performance modal populates live after every chat interaction:

| Metric | Source |
|:---|:---|
| **Latency (ms)** | Client-side `Date.now()` round-trip diff |
| **Token Usage** | Prompt + completion tokens from backend |
| **Confidence / RAG Score %** | Cross-encoder groundedness via FlashRank |
| **Classified Intent** | LangGraph supervisor routing decision |
| **Active Session ID** | Current `SES-XXXX` session identifier |
| **Grounded Citations** | `chunk_id` source references from Qdrant |

Every chat bubble also shows inline `⚡ {latency}ms · {tokens}t` performance pills. Clicking any pill opens the telemetry modal pre-populated with that turn's exact metrics.

---

### 🛡️ Graceful Error Handling — 9 Production Guardrails

| # | Guardrail | Behaviour |
|:---|:---|:---|
| 1 | Input Sanitization | Rejects blank queries, whitespace abuse, prompt injection |
| 2 | 404 on Missing Sessions | `/api/sessions/{id}` returns clean HTTP 404, never 500 |
| 3 | Slot-Filling | Prompts for missing order IDs when intent is recognized |
| 4 | Tool Fault Tolerance | `try/except` around all external service calls |
| 5 | LLM Circuit Breaker | Deterministic fallback during API timeouts or rate limits |
| 6 | RAG Groundedness Gate | Escalates when no chunk clears the confidence threshold |
| 7 | Safe State Transitions | Recovers from corrupted agent states mid-graph |
| 8 | WebSocket Auto-Reconnect | Inline toast notifications, no disruptive browser alerts |
| 9 | Ticket Reference Tracking | All escalations emit unique `TCK-XXXX` tracking codes |

---

### 🔄 CI/CD Pipeline & Cloud Deployment

- **Frontend → Netlify** — Auto-deploys from `main` branch, global CDN, SPA redirect rules via `netlify.toml`
- **Backend → Render** — Dockerfile-based deploy with `gunicorn + uvicorn` workers, auto-deploys on push
- **Vector DB → Qdrant Cloud** — Managed, persistent vector collection
- **Database → Supabase** — Managed PostgreSQL with Row-Level Security (RLS) migrations
- **Cache → Redis** — Docker Compose for local dev; cloud Redis/Upstash for production
- **Supabase Anti-Sleep** — Async background task pings Supabase every 12 hours to prevent free-tier pausing

---

### 💻 Modern Streaming Frontend

- **Bi-directional WebSocket streaming** with transparent REST API fallback when offline
- **Dual theme system** — Dark mode (default) and slate-gray light mode, WCAG contrast compliant
- **Lifecycle state pills** — `INIT` → `ROUTING` → `RAG` → `DONE` rendered live during inference
- **Session history sidebar** — Restores past conversations, telemetry, and active highlights across page reloads
- **Live visitor counter** — Server-persisted global session count (`GET /api/visitors`)

---

## 🗂️ Repository Structure

```text
ResolveX/
├── Backend/
│   ├── agent/                    # LangGraph multi-agent orchestrator
│   │   ├── graph.py              # StateGraph lifecycle & compilation
│   │   ├── nodes.py              # Specialist nodes: Policy, Orders, Action, Escalation
│   │   ├── router.py             # Intent classification & supervisor triage
│   │   └── state.py              # Pydantic AgentState & conversation context
│   ├── api/                      # FastAPI endpoints & WebSocket handlers
│   │   ├── routes.py             # REST: /api/chat, /health, /api/visitors, sessions
│   │   ├── schemas.py            # ChatRequest · ChatResponse · HealthResponse schemas
│   │   └── websocket.py          # Bi-directional WebSocket streaming handler
│   ├── db/                       # Database clients
│   │   ├── qdrant_client.py      # Qdrant collection manager & vector client
│   │   └── supabase_client.py    # Supabase PostgreSQL connection
│   ├── rag/                      # Knowledge base & RAG pipeline
│   │   ├── chunking.py           # PDF text extraction & semantic chunking
│   │   ├── embeddings.py         # Dense vector embeddings generator
│   │   ├── ingest.py             # Knowledge base indexing entry point
│   │   ├── reranking.py          # FlashRank cross-encoder & RRF rerankers
│   │   └── retrieval.py          # Hybrid retrieval & groundedness threshold filter
│   ├── schemas/                  # Pydantic domain models
│   │   ├── customer.py
│   │   ├── order.py
│   │   ├── payment.py
│   │   └── ticket.py
│   ├── services/                 # Business service layer
│   │   ├── chat_service.py       # Chat session & message persistence
│   │   ├── customer_service.py
│   │   ├── order_service.py
│   │   ├── payment_service.py
│   │   ├── redis_cache.py        # Redis cache client & policy caching
│   │   └── ticket_service.py
│   └── main.py                   # ASGI app factory, lifespan hooks & keep-alive task
├── data/
│   ├── knowledge_base/           # Policy source PDF documents
│   ├── orders.json               # Seed orders: ORD-1001, ORD-8832, ORD-5511
│   └── visitor_count.txt         # Persistent global visitor counter
├── database/
│   └── migrations/
│       └── 001_initial_schema.sql  # 7 relational tables, RLS policies & indexes
├── docs/
│   ├── architecture.md
│   ├── implementation_guide.md
│   └── screenshots/              # Add your UI screenshots here
├── frontend/
│   ├── index.html                # Single-page chat interface & modals
│   ├── script.js                 # WebSocket client, telemetry binding & theme engine
│   └── config.js                 # Runtime API URL configuration
├── tests/                        # 229 automated tests (100% pass rate)
│   ├── test_agent_nodes.py
│   ├── test_agent_orchestrator.py
│   ├── test_agent_router.py
│   ├── test_api_endpoints.py
│   ├── test_guardrails_error_handling.py
│   ├── test_rag_retrieval.py
│   ├── test_rag_reranking.py
│   ├── test_redis_cache.py
│   └── ...
├── Dockerfile                    # Multi-stage production container
├── docker-compose.yml            # Local dev: API + Redis + Qdrant
├── netlify.toml                  # Netlify SPA redirect configuration
├── requirements.txt              # Python production dependencies
└── README.md
```

---

## 🌐 Production Deployment

| Component | Platform | URL |
|:---|:---|:---|
| **Frontend Interface** | Netlify | [resolvex-ai.netlify.app](https://resolvex-ai.netlify.app/) |
| **Backend API** | Render | [resolvex-bd8o.onrender.com](https://resolvex-bd8o.onrender.com) |
| **Swagger / OpenAPI Docs** | Render | [resolvex-bd8o.onrender.com/docs](https://resolvex-bd8o.onrender.com/docs) |
| **Vector Database** | Qdrant Cloud | Managed persistent vector collection |
| **Relational Database** | Supabase | Managed PostgreSQL with RLS |

---

## 🚀 Local Setup & Installation

### Prerequisites

- **Python 3.10+** (tested on Python 3.12)
- **Docker & Docker Compose** — for Redis + Qdrant local services
- A modern web browser (Chrome, Edge, Firefox, Safari)

---

### Step 1 — Clone the Repository

```bash
git clone https://github.com/princeVerma73/ResolveX.git
cd ResolveX
```

### Step 2 — Create Virtual Environment & Install Dependencies

```bash
python -m venv .venv

# Activate — Windows
.venv\Scripts\activate

# Activate — Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### Step 3 — Configure Environment Variables

```bash
cp .env.example .env
```

Open `.env` and fill in your credentials:

```env
# Supabase (Required)
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_PUBLISHABLE_KEY=your-supabase-anon-key

# LLM API Key (Required for agent inference)
GEMINI_API_KEY=your-google-gemini-api-key

# Redis Cache
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
# REDIS_URL=redis://default:password@host:port   # Cloud Redis / Upstash

# Qdrant Vector DB
QDRANT_URL=http://localhost:6333
# QDRANT_API_KEY=your-qdrant-cloud-api-key       # Required for Qdrant Cloud

# CORS
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

### Step 4 — Start Supporting Services (Docker)

```bash
docker-compose up -d
```

Starts **Redis** (`localhost:6379`) and **Qdrant** (`localhost:6333`).

### Step 5 — Ingest the Policy Knowledge Base

```bash
python -m Backend.rag.ingest
```

Chunks, embeds, and indexes all PDF documents from `data/knowledge_base/` into Qdrant.

### Step 6 — Start the Backend API Server

```bash
uvicorn Backend.main:app --host 0.0.0.0 --port 8000 --reload
```

- API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`

### Step 7 — Launch the Frontend

```bash
# Serve with local HTTP server
python -m http.server 3000 --directory frontend
# Then visit: http://localhost:3000
```

---

## 🧪 Test Suite

**229 automated tests** covering every system layer: Pydantic domain models, Supabase schema migrations, RAG retrieval and reranking pipelines, LangGraph agent nodes, REST + WebSocket endpoints, Redis caching, and all 9 production guardrails.

```bash
# Full suite
pytest

# By category
pytest tests/test_agent_orchestrator.py            # Multi-agent pipeline
pytest tests/test_guardrails_error_handling.py     # All 9 guardrails
pytest tests/test_rag_retrieval.py tests/test_rag_reranking.py    # RAG pipeline
pytest tests/test_api_endpoints.py tests/test_redis_cache.py      # API + cache
pytest tests/test_domain_models.py tests/test_database_schema.py  # Data layer
```

**Status:** ✅ 229 passed · 0 failed · 0 skipped

---

## 📡 API Reference

### REST Endpoints

| Method | Endpoint | Description |
|:---|:---|:---|
| `GET` | `/health` | System diagnostics & service connectivity check |
| `POST` | `/api/chat` | Synchronous REST chat (returns `tokens`, `rag_score`, `latency_ms`) |
| `GET` | `/api/sessions/{session_id}` | Full session message history (HTTP 404 on missing session) |
| `GET` | `/api/visitors` | Global live visitor counter (server-persisted) |

### WebSocket Interface

**Endpoint:** `ws://localhost:8000/ws/chat/{session_id}`

**Client → Server:**
```json
{ "query": "What is your 30-day refund policy?" }
```

**Server → Client events:**

| Event | Key Payload Fields | Description |
|:---|:---|:---|
| `start` | `session_id`, `query` | Analysis initialized |
| `routing` | `status` | Live intent classification status |
| `retrieval` | `chunks_count`, `citations` | RAG chunks retrieved from Qdrant |
| `token` | `delta` | Incremental response token (word-by-word) |
| `done` | `response`, `intent`, `citations`, `tokens`, `rag_score` | Final answer + full telemetry |
| `error` | `message` | Handled error with descriptive detail |

---

## 🛠️ Tech Stack

| Layer | Technology | Role |
|:---|:---|:---|
| **Web Framework** | FastAPI 0.110+ | Async REST API & WebSocket server |
| **ASGI Server** | Uvicorn + Gunicorn | Production process management |
| **Agent Orchestration** | LangGraph | Multi-agent StateGraph execution |
| **LLM** | Google Gemini (`google-genai`) | Intent routing & response generation |
| **Vector Database** | Qdrant Cloud | Dense semantic search & embedding storage |
| **Neural Reranker** | FlashRank + RRF | Cross-encoder groundedness scoring |
| **Relational DB** | Supabase PostgreSQL | Orders, sessions, tickets, customers |
| **Cache Layer** | Redis | Sub-10ms response caching for repeated queries |
| **Data Validation** | Pydantic v2 | Strict schema enforcement at all boundaries |
| **Frontend** | Vanilla JS + Tailwind CSS | Minimalist real-time streaming chat interface |
| **Frontend Hosting** | Netlify | CDN-cached SPA with auto-deploy from `main` |
| **Backend Hosting** | Render | Dockerfile-based container deployment |
| **Containerization** | Docker + Docker Compose | Local dev orchestration |
| **Testing** | pytest + pytest-asyncio | 229 tests, 100% pass rate |

---

## 📦 Mock Orders for Testing

| Order ID | Status | Carrier | ETA | Items |
|:---|:---|:---|:---|:---|
| `ORD-1001` | ✅ Delivered | FedEx | — | 1× Wireless Headphones |
| `ORD-8832` | 🚚 In Transit | FedEx | Tomorrow | 1× Mechanical Keyboard |
| `ORD-5511` | ⏳ Processing | UPS | In 2 days | 1× Smart Fitness Band |

**Sample queries to try on the live demo:**
- *"Where is my order ORD-8832?"*
- *"What is your refund policy for electronics?"*
- *"I want to cancel order ORD-5511."*
- *"My laptop won't connect to Wi-Fi after a software update."*

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/your-feature-name`
3. Follow [Conventional Commits](https://www.conventionalcommits.org/) for commit messages
4. Ensure all tests pass: `pytest`
5. Open a pull request with a clear description of your changes

---

## 📄 License

This project is open-source and licensed under the [MIT License](LICENSE).

---

<div align="center">

Built with ❤️ by [Prince Verma](https://github.com/princeVerma73)

**[🚀 Live Demo](https://resolvex-ai.netlify.app/) · [📖 API Docs](https://resolvex-bd8o.onrender.com/docs) · [🐛 Report a Bug](https://github.com/princeVerma73/ResolveX/issues)**

</div>
