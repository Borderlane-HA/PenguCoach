# AI Analysis & Training Planning

PenguCoach provides a bounded, source-aware AI layer on top of the deterministic Garmin/FIT pipeline.

## Data contract

The LLM never receives a database connection and never operates on Garmin directly. The API builds a compact JSON context first.

For an activity, the context separates:

- `activity.garmin`: official Garmin summary values such as distance, duration, HR, speed, elevation, power, cadence, training load and training effect when available.
- `activity.pengucoach`: deterministic locally calculated FIT metrics such as HR drift, power drift, aerobic decoupling, pace consistency and data quality.
- `activity.fit_analytics`: locally derived descriptive FIT statistics.
- `activity.splits`: deterministic distance splits, capped before reaching the LLM.
- `lookback`: recent activity, sleep, HRV and daily-health data for the selected lookback window.
- `lookback.summary_3d` / `summary_7d`: deterministic workload summaries used to discuss whether the recent pattern is relatively light, balanced or heavy without diagnosing overtraining.

Missing measurements remain `null`; raw Garmin payloads and raw FIT sample streams are not sent to the LLM.

## Activity deep analysis

The Activity Detail page exposes **AI Analyse / AI analysis**.

The user can select:

- eligible model (the configured task default is preselected),
- lookback: activity only, previous 3 days, or previous 7 days,
- maximum response tokens within the selected model/provider/context capabilities,
- an editable analysis prompt.

The shipped deep-analysis prompt asks the model to cover activity quality, HR/power/pace/cadence/elevation, splits, recent load/recovery context, strengths, watch-outs and a practical next-session suggestion. It explicitly prohibits inventing missing values and avoids treating training-load patterns as a medical diagnosis.

AI results are persisted in `ai_runs` and the latest result is shown again after reloading the activity.

## Training plans

The Training page can generate a periodized plan for:

- muscle gain,
- cardio/endurance,
- hybrid strength + endurance,
- cycling endurance,
- 5K / 10K / half-marathon / marathon running,
- strength,
- general fitness,
- mobility,
- custom goals.

Inputs include experience, plan duration, days per week, typical session duration, available equipment, constraints and a free-text goal. The user explicitly selects a recent 3, 7, 14, 21 or 28 day context window (7 days by default) and which data categories may be supplied to the model: training/FIT analytics, Garmin zones, sleep/HRV, recovery/stress and optional steps/hydration. No hidden 28-day window is appended. Plans are persisted in `ai_runs` together with the selected context metadata. Newly generated plans also carry a validated structured calendar representation; users can review/select sessions and, after explicitly enabling the separate Garmin workout exporter, schedule supported structured workouts in Garmin Connect. Normal Garmin data synchronization remains read-only.

Local Ollama requests are streamed. This exposes approximate live output-token progress and permits cancellation of a running generation. The final Ollama `eval_count` is stored as the exact output-token count when supplied by Ollama. Large structured plans with more than 12 sessions are generated in validated week segments and merged into one plan, preventing one oversized JSON response from consuming the entire output budget.

## Model routing

Admin → AI defines separate routes for:

- `coach_chat`
- `activity_analysis`
- `training_plan`

Each route supports a primary and fallback model, a predefined prompt, a maximum output-token budget and a maximum input-context character budget. If a route has no primary model, PenguCoach falls back to the first eligible enabled model. User privacy rules are still enforced: when cloud health AI is disabled, only local providers are eligible.

## Cost and context controls

Output limits are passed to providers as:

- OpenAI / OpenAI-compatible: `max_tokens`
- Anthropic: `max_tokens`
- Ollama: `num_predict`

The configured task budget is the default. The UI may request a larger or smaller value; PenguCoach then clamps the effective request to the selected model/provider limit and to the available context window.

Input context is generated from normalized summaries and deterministic analytics rather than thousands of FIT samples. A second context-size guard progressively trims lower-priority lists when necessary. The UI shows an approximate token equivalent (`characters / 4`) as a planning estimate; actual tokenizer usage varies by model.

When a provider returns usage information, PenguCoach surfaces the input/output token counts and stores them with the AI run metadata.
