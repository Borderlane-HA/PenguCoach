# PenguCoach product roadmap

This roadmap keeps the Adaptive Coach direction explicit while the UI follows a progressive-disclosure rule: the normal path stays simple, deeper controls appear only when they are needed, and mobile users retain the same capabilities without desktop-sized information density.

## Adaptive Coach priorities

| Priority | Capability | Status in alpha.44 | Next meaningful step |
| --- | --- | --- | --- |
| 1 | Coach Memory v1 | **Shipped + suggestions v1** | Suggestions require repeated explicit evidence and user confirmation; never create hidden permanent rules. |
| 2 | Adaptive training plans | **Foundation shipped** | Broaden adaptation triggers and Alpha.47 ships a reviewed rolling seven-day adaptation and short variants; expand longer-term adaptation only with adequate data. |
| 3 | Daily Readiness / traffic light | **Shipped (v1)** | Improve trend context and calibration without turning it into a medical score. |
| 4 | Weather + training | **Shipped (v1)** | Forecast/risk is shown on near-term outdoor plan sessions; reviewed indoor alternatives are available when conditions are unfavorable. |
| 5 | Coach chat with context | **Shipped (v1)** | Deepen plan-aware follow-ups and reuse the same structured decision context as adaptive planning. |
| 6 | Training load & trends | **Shipped (v1)** | 7/28-day load, volume, sport mix and understandable trend labels are deterministic and compact. |
| 7 | Manual post-workout feedback | **Shipped (v1)** | Use RPE/difficulty/discomfort more consistently in adaptation and trends. |
| 8 | Plan conflict detection | **Shipped (v1)** | Detect saved training-day constraints, unusual duration, back-to-back hard sessions and other saved PenguCoach plan sessions (with Garmin-export enrichment); external calendars can follow later. |
| 9 | AI Decision Log | **Shipped (v1)** | Accepted adaptive changes persist before/after snapshots plus structured Readiness/weather reasons. |
| 10 | Coach Dashboard | **Planned** | Build a concise start view around Today, Readiness, next session, weekly progress, load, weather and 1–2 actionable Coach notes. |

## UI placement principles

- **Today:** what matters now; Readiness, today’s session and a small number of actionable notes.
- **Health:** health/recovery measurements and their trends.
- **Activities:** completed workout history and detailed activity analysis.
- **Training:** create and manage plans. Alpha.43 uses a guided four-step planner and collapsed plan/week/session hierarchy.
- **AI Coach:** questions, explanations and proposed decisions/adaptations.
- **Future Coach Dashboard:** cross-domain overview only; it should summarize, not duplicate every detail from the specialist pages.

## Product rules for future releases

1. Prefer a useful default plus an **Advanced/Customize** disclosure over exposing every switch at once.
2. Keep destructive or schedule-changing actions explicit and reviewable.
3. Use deterministic calculations for load/readiness/conflicts where practical; let the LLM explain and coach from structured facts rather than inventing measurements.
4. Every recommendation should be traceable to the data actually supplied to the model.
5. Design and test desktop, tablet and phone flows together. Features must not disappear merely because the viewport is small.
6. Do not turn Training into a second AI Studio. Model/token/prompt controls remain available but secondary to the coaching workflow.

## Health Development (Alpha.45)

The Health view now combines fitness, training load, efficiency and recovery with progressive disclosure and professional interactive charts. Provider VO₂ remains authoritative; PenguCoach may calculate a clearly-labelled fallback estimate only when provider data is absent. Longer-term work can add training-block annotations and richer correlations without turning the Health page into another configuration dashboard.

## Plan Evolution (Alpha.47)

Reviewed rolling weeks, time-aware short variants, duration-aware plan matching, explicit one-to-one activity assignments and source freshness are shipped. See [PLAN_EVOLUTION.md](PLAN_EVOLUTION.md). Long-term individualized recovery calibration remains future work.
