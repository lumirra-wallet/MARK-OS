# MARK AI OS — Architecture

## Overview

MARK (Modular Autonomous Reasoning Kernel) is a full-stack AI engineering assistant. The architecture is split into three layers:

```
┌─────────────────────────────────────────────────────────┐
│  React Dashboard  (artifacts/mark-dashboard)            │
│  Vite + TypeScript + Zustand + Tailwind                 │
│  Connects via REST + WebSocket to the Python backend    │
└──────────────────────┬──────────────────────────────────┘
                       │  HTTP + WS  (/mark-api/*)
┌──────────────────────▼──────────────────────────────────┐
│  FastAPI Backend  (smartagent/server/)                   │
│  REST API, WebSocket stream, provider wiring            │
│  Routers: api.py · api_system · api_providers ·         │
│           api_diagnostics · api_code · api_git ·        │
│           api_terminal · api_jobs · api_eval · ...      │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  MARK Core  (smartagent/)                               │
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ LLM Layer   │  │ Storage      │  │ Vector Store  │  │
│  │ github      │  │ local(JSON)  │  │ keyword       │  │
│  │ openai      │  │ postgres     │  │ chroma        │  │
│  │ anthropic   │  │ (SQLAlchemy) │  │ pgvector      │  │
│  │ ollama      │  └──────────────┘  └───────────────┘  │
│  └─────────────┘                                        │
│                                                         │
│  Brain · Mind · Executive · Workers · Memory · Tools    │
└─────────────────────────────────────────────────────────┘
```

## Directory layout

```
mark-ai/
├── smartagent/             # Python backend + AI core
│   ├── server/             # FastAPI app, routers, WebSocket
│   ├── llm/                # LLM provider abstraction
│   │   ├── base.py         # LLMProvider protocol
│   │   ├── factory.py      # provider selection + wiring
│   │   ├── github_provider.py
│   │   ├── openai_provider.py
│   │   ├── anthropic_provider.py
│   │   └── ...
│   ├── storage/            # Storage abstraction
│   │   ├── base.py         # StorageProvider ABC
│   │   ├── local_storage.py
│   │   ├── postgres_storage.py
│   │   └── factory.py
│   ├── vector/             # Vector store abstraction
│   │   ├── base.py         # VectorProvider ABC
│   │   ├── keyword_provider.py
│   │   ├── chroma_provider.py
│   │   ├── pgvector_provider.py
│   │   └── factory.py
│   ├── brain/              # Core agent loop
│   ├── mind/               # Homeostasis, identity
│   ├── executive/          # Planning, workers, scheduler
│   ├── memory/             # Long-term memory vault
│   ├── tools/              # Tool engine
│   ├── workspace/          # Workspace management
│   └── config/             # Settings dataclass
│
├── artifacts/
│   ├── mark-dashboard/     # React frontend
│   └── mark-api/           # Thin Replit artifact wrapper
│
├── docs/                   # This documentation
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Configuration

All configuration is via environment variables. See `.env.example` for the full list.

Key variables:

| Variable          | Default        | Description                              |
|-------------------|----------------|------------------------------------------|
| ACTIVE_PROVIDER   | auto           | LLM provider: github/openai/anthropic/ollama |
| DATABASE_PROVIDER | sqlite         | Storage backend: sqlite/postgres         |
| VECTOR_PROVIDER   | keyword        | Vector store: keyword/chroma/pgvector    |
| DATABASE_URL      | —              | PostgreSQL connection string             |
| GITHUB_TOKEN      | —              | GitHub Models / personal access token   |
| OPENAI_API_KEY    | —              | OpenAI API key                           |
| ANTHROPIC_API_KEY | —              | Anthropic API key                        |
| OLLAMA_HOST       | localhost:11434 | Ollama server URL                       |

## Startup sequence

On server start (`smartagent/server/app.py` lifespan):

1. Load configuration (env vars, .env file)
2. Auto-detect workspace from `git rev-parse --show-toplevel`
3. Storage provider initialized (LocalStorage or PostgreSQL)
4. Vector store initialized (keyword, Chroma, or pgvector)
5. LLM provider selected (auto-detect from available tokens)
6. FastAPI routers mounted
7. WebSocket manager started
8. Server ready

## Adding a new provider

To add e.g. `GeminiProvider`:

```python
# smartagent/llm/gemini_provider.py
class GeminiProvider:
    _exclude_from_discovery = True

    def chat(self, messages, **kwargs): ...
    def stream_chat(self, messages, **kwargs): ...
    def embed(self, text, **kwargs): ...
    def embeddings(self, text, **kwargs): ...
    def list_models(self): ...
    def health(self): ...
    def switch_model(self, model_name): ...
```

Then add `"gemini"` to `_VALID_PROVIDERS` in `smartagent/llm/factory.py` and wire it in `_wire_provider()`.
No other files need changing.
