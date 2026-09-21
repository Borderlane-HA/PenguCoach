# PenguCoach AI Studio — alpha.5

## Goals

Alpha.5 separates three concepts that were mixed together in alpha.4:

1. **Model routing** — which configured model handles Chat, Activity Analysis or Training Planning.
2. **Context window** — how many tokens the model may use for prompt + data + response. Ollama receives this as `num_ctx`.
3. **Response budget** — the maximum generated answer length. Ollama receives this as `num_predict`.

The default context window is 8192 tokens. Default response budgets are 2500 for Coach Chat, 3500 for Activity Analysis and 4500 for Training Plans. All limits remain configurable in AI Studio.

## Language

German and English prompts are stored separately. The web UI sends its active language with each AI job, so the model receives an explicit German or English system/task prompt rather than relying on language detection.

## Background jobs

Long AI requests are queued in Celery as background jobs on the existing `maintenance` queue so the alpha.4 worker configuration can consume them immediately after an update. The browser receives a task ID immediately and polls `/api/v1/jobs/<task-id>`. Active IDs are retained in local browser storage so an Activity Analysis or Training Plan can survive a page reload.

## Truncation detection

PenguCoach stores provider stop reasons where available. A response is also considered truncated when reported output tokens reach the configured output ceiling. The UI warns the user instead of presenting an incomplete answer as final.

## Smart Coach context

Coach Chat offers Auto / none / 7d / 28d context modes. Auto only adds Garmin/FIT context when the question appears related to training, recovery or health metrics. General questions can therefore avoid unnecessary token use.

## Provider mapping

- Ollama: `num_ctx` + `num_predict`
- OpenAI / OpenAI-compatible: provider model context remains authoritative; PenguCoach limits its prepared context and sets `max_tokens`
- Anthropic: provider model context remains authoritative; PenguCoach limits its prepared context and sets `max_tokens`

