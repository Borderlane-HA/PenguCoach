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
- OpenRouter — `https://openrouter.ai/api/v1`
- Generic OpenAI-compatible endpoints

IONOS uses a Bearer token/JWT; an expired token must be renewed. Gemini uses a Gemini API key. xAI uses an xAI API key. API keys/tokens are encrypted before persistence.

## Model discovery

The connection test reads authentication/catalogue endpoints only. It does not generate a paid answer and cannot certify every model's generation capabilities. Saved providers can be queried for their model catalogue. Discovered identifiers can be added directly to PenguCoach. Where the provider exposes context/output capability metadata, those limits can be stored with the model; otherwise they can be edited manually.

## Language

German and English prompts are stored separately. The web UI sends its active language with each AI job, so the model receives an explicit German or English system/task prompt rather than relying on language detection.

## Background jobs and cancellation

Long AI requests run as Celery background jobs. The browser receives a task ID and polls the job endpoint. Active IDs are retained in local browser storage so a Coach request, Activity Analysis or Training Plan can survive a page reload.

Ollama output is streamed, which enables live approximate output-token progress and prompt cancellation while generation is running. Completed Ollama responses use the provider's final token counters when available.

Cloud requests also observe cancellation and close the local pending HTTP request promptly. A remote server may continue work after disconnect; PenguCoach cannot guarantee that cancellation stops provider billing. Missing usage is recorded as unknown, not a zero-token successful request. Known counts returned just before cancellation are retained in the usage ledger.

## Budgets and model controls

Saved response profiles determine the initial output budget on every page load. An explicit per-request override remains possible within model and context limits. This is a maximum, not a forced output length. The complete latest Coach question is preserved; if it cannot fit, the request fails before contacting the model instead of silently cutting its beginning.

Native OpenAI uses `max_completion_tokens` and omits incompatible temperature settings for recognized reasoning models. Documented Gemini, Grok, OpenRouter and supported Claude effort controls follow the response profile. Ollama reads `/api/show` thinking metadata once per model/hour: disable thinking when supported, otherwise use a supported level. Mandatory-thinking models may still consume output tokens before visible text appears. Generic endpoints retain conservative controls; unknown proprietary parameters are not assumed to work.

Cloud training plans receive a small portable JSON schema; Ollama retains the request-specific generation schema. Explicit HTTP 400/422 rejections of optional formatting/reasoning/sampling parameters permit a bounded negotiation, cached per model for an hour. Authentication, quota, rate-limit and server errors are not blindly retried as parameter failures. Rejected schemas fall back to the explicit JSON instructions and the same server validation; unsupported model APIs are not silently replaced with another model.

## Training-plan generation

Large structured plans are not forced through one huge JSON completion. Plans with more than 12 requested sessions are split into small week segments. Each segment is validated independently, week numbers are remapped, and PenguCoach merges the segments into one structured Garmin-ready plan. Every plan, including short plans, is checked against the requested week count and minimum sessions in each week. An invalid section receives at most one automatic repair using the same user-selected per-call ceiling. A successful section is committed before the next request starts. Format failures and network interruptions offer a retry of the pending section without increasing its budget; a genuine output limit retains the explicit +8,000 action. Validated earlier weeks are never regenerated as part of that recovery. Interrupted requests with no reported usage remain visible as unknown in usage totals.

Generation instructions are compact and the changing segment/repair controls follow the common system/data prefix. Context omits null fields while preserving measurements, provenance and full goal constraints. Provider caches may benefit from the stable prefix; savings and response quality depend on the actual model and provider. Technical details retain per-attempt validation and available native Ollama timing. No fixed speed-up is claimed.

## Privacy

Cloud-health AI remains disabled per user by default. External providers are not eligible for health/training context until the user explicitly permits cloud AI in Privacy settings. Local Ollama remains available without that cloud permission.


## Coach companion and output-limit troubleshooting

See [COACH_COMPANION.md](COACH_COMPANION.md) for memory, history, daily briefings and plan integration. Recognized output limits, including Claude's context-window stop reason, store a recoverable draft even when no visible answer was generated. Continue from the result rather than rerunning the entire analysis. Context and hard model limits remain authoritative. Both compatibility APIs and the GUI background jobs use the same validated engine.
