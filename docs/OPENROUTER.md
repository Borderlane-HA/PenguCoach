# OpenRouter

Added in v0.1.0-alpha.60 for [feature request #1](https://github.com/Borderlane-HA/PenguCoach/issues/1).

## Einrichtung / Setup

1. **Admin → KI / AI → Provider & Modelle / Providers & models** öffnen.
2. **OpenRouter** auswählen. Die Basis-URL wird mit `https://openrouter.ai/api/v1` vorbelegt.
3. Einen OpenRouter API Key eingeben und **Verbindung testen / Test connection** anklicken. Der Test validiert den Schlüssel und lädt den Modellkatalog; er startet keine Modellantwort und sendet keine Gesundheits- oder Trainingsdaten.
4. **Provider speichern / Save provider**. Die gefundene Modellliste kann danach direkt verwendet werden. Bei einem bereits gespeicherten Provider stattdessen **Erkennen / Discover** verwenden; der verschlüsselt gespeicherte Schlüssel wird wiederverwendet.
5. Über **Modelle durchsuchen / Search models** nach Name oder Modell-ID suchen und das gewünschte Modell **hinzufügen / add**. Weitere Ergebnisse lassen sich einblenden. Angezeigte Modell-IDs einschließlich Anbieterpräfix und etwaiger Suffixe werden unverändert verwendet.
6. Das gespeicherte Modell oben der gewünschten Aufgabe als Standard oder Fallback zuordnen und die Aufgabeneinstellung speichern. Dies ist für **Coach Chat**, **Aktivitätsanalyse / Activity analysis** und **Trainingsplanung / Training planning** verfügbar.
7. Für KI-Anfragen mit Gesundheits- oder Trainingsdaten muss Cloud-KI in den Datenschutzeinstellungen ausdrücklich freigegeben sein. Das Speichern oder Testen eines Providers schaltet diese Freigabe nicht automatisch ein. OpenRouter gilt immer als externer Cloud-Provider.

In English: open Admin → AI → Providers & models, select OpenRouter, enter your API key, test and save. Search the discovered models, add one, then assign it to a task and save that task. An existing provider's Discover action reuses its stored key. Cloud health/training-data permission must be enabled separately before generation.

## Model limits, usage and costs

- Discovery imports text-input/text-output models from the full catalog. Audio-only, embedding-only and models with reported limits below PenguCoach's minimum are omitted. Multimodal models that also support text remain available for text requests.
- Context size uses the smaller positive catalog/provider context limit when both are supplied. Output size uses `top_provider.max_completion_tokens`. Unknown limits stay unset; imported values are bounded by the existing model-editor limits.
- PenguCoach continues to apply the configured task/context/output budgets and reports provider token usage and truncated answers. Model availability, account permissions, free-model limits and credit limits are controlled by OpenRouter and can change after discovery.
- Catalog prices are USD per token. They are **not** automatically copied into PenguCoach's EUR-per-million-token fields. Enter EUR prices manually if cost statistics are needed; otherwise requests stay unpriced. Token usage is still recorded.
- One valid key/catalog test does not guarantee access to every catalog model or enough credits for a later completion. The catalog can include models outside a key's permitted selection.
- Cloud generation follows the existing non-streaming OpenAI-compatible path. There are no new database migrations, environment variables or runtime dependencies.

## Errors

The admin connection/discovery UI translates fixed error codes for missing or invalid keys, credit limits, denied access, rate limits and unavailable upstreams. Raw upstream error messages and key/account response data are not returned. Generation also rejects provider error envelopes delivered with HTTP 200 and does not treat error/content-filtered partial answers as successful responses. Network/timeouts continue to use the existing request error handling.

## API details and references

- Bearer authentication; optional static attribution header `X-OpenRouter-Title: PenguCoach`. No instance URL is sent as a referrer.
- `GET /api/v1/key` verifies credentials because the models endpoint itself is public. The account/key details are discarded.
- `GET /api/v1/models` discovers model IDs, names and limits without the generic provider's 100-model truncation.
- `POST /api/v1/chat/completions` performs the selected task with the exact model identifier and common token budgets.

Official references checked during implementation:

- [API overview](https://openrouter.ai/docs/api-reference/overview)
- [Model catalog](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties)
- [Current API key](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key)

## Validation

The release includes automated tests using simulated OpenRouter responses for key validation, full-catalog discovery, imported limits, encrypted secret storage, safe errors, all three tasks, usage/truncation and cloud-only enforcement. Browser checks cover setup, saved-key discovery, catalog search/progressive display, model import and task assignment with simulated API endpoints. No paid completion or live private API key is needed for these tests.
