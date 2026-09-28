# PenguCoach product roadmap

This roadmap keeps the Adaptive Coach direction explicit while the UI follows a progressive-disclosure rule: the normal path stays simple, deeper controls appear only when they are needed, and mobile users retain the same capabilities without desktop-sized information density.

## Adaptive Coach priorities

| Priority | Capability | Status in alpha.43 | Next meaningful step |
| --- | --- | --- | --- |
| 1 | Coach Memory v1 | **Shipped** | Continue improving suggestions for user-confirmed memories; never create hidden permanent rules. |
| 2 | Adaptive training plans | **Foundation shipped** | Broaden adaptation triggers and plan-level rescheduling while keeping preview + explicit confirmation. |
| 3 | Daily Readiness / traffic light | **Shipped (v1)** | Improve trend context and calibration without turning it into a medical score. |
| 4 | Weather + training | **Partially shipped** | Weather already informs plan generation and relevant Coach chat. Next: show forecast/risk directly on near-term planned sessions and offer indoor alternatives. |
| 5 | Coach chat with context | **Shipped (v1)** | Deepen plan-aware follow-ups and reuse the same structured decision context as adaptive planning. |
| 6 | Training load & trends | **Planned** | Add understandable acute/chronic load, weekly volume, sport mix and trend labels; avoid dashboard overload. |
| 7 | Manual post-workout feedback | **Shipped (v1)** | Use RPE/difficulty/discomfort more consistently in adaptation and trends. |
| 8 | Plan conflict detection | **Planned** | Detect existing planned/Garmin sessions and explicit availability constraints; external calendar support can follow later. |
| 9 | AI Decision Log | **Planned** | Store/show structured reasons behind meaningful recommendations or accepted plan changes. |
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
