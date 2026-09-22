# PenguCoach AI Studio

## Purpose

AI Studio separates four concerns:

1. **Providers** — where inference runs.
2. **Models** — concrete model identifiers plus their known context/output limits.
3. **Task routing** — which model handles Coach, Activity Analysis or Training Planning.
4. **Task defaults** — starting context and response budgets plus task prompts.

Task budgets are defaults. A task UI may request a larger budget when the selected model/provider supports it; the model context window and any configured provider maximum remain authoritative.

## Supported providers

PenguCoach currently provides first-class presets for:

- Ollama — local `/api/chat`
- OpenAI — `https://api.openai.com/v1`
- Anthropic / Claude — `https://api.anthropic.com/v1`
- IONOS AI Model Hub — OpenAI-compatible `https://openai.inference.de-txl.ionos.com/v1`
- Google Gemini — OpenAI-compatible `https://generativelanguage.googleapis.com/v1beta/openai`
- xAI / Grok — OpenAI-compatible `https://api.x.ai/v1`
- Generic OpenAI-compatible endpoints

IONOS uses a Bearer token/JWT; an expired token must be renewed. Gemini uses a Gemini API key. xAI uses an xAI API key. API keys/tokens are encrypted before persistence.

## Model discovery

Saved providers can be queried for their model catalogue. Discovered identifiers can be added directly to PenguCoach. Where the provider exposes context/output capability metadata, those limits can be stored with the model; otherwise they can be edited manually.

## Language

German and English prompts are stored separately. The web UI sends its active language with each AI job, so the model receives an explicit German or English system/task prompt rather than relying on language detection.

## Background jobs and cancellation

Long AI requests run as Celery background jobs. The browser receives a task ID and polls the job endpoint. Active IDs are retained in local browser storage so a Coach request, Activity Analysis or Training Plan can survive a page reload.

Ollama output is streamed, which enables live approximate output-token progress and prompt cancellation while generation is running. Completed Ollama responses use the provider's final token counters when available.

## Training-plan generation

Large structured plans are not forced through one huge JSON completion. Plans with more than 12 requested sessions are split into small week segments. Each segment is validated independently, week numbers are remapped, and PenguCoach merges the segments into one structured Garmin-ready plan. If one compact segment alone reaches its output cap, only that segment is retried with a larger allowance.

## Privacy

Cloud-health AI remains disabled per user by default. External providers are not eligible for health/training context until the user explicitly permits cloud AI in Privacy settings. Local Ollama remains available without that cloud permission.
