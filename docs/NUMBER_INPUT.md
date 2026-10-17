# Number entry

Available from v0.1.0-alpha.62. All 44 numeric fields use one shared `NumberInput` control, including training weeks/days/duration, AI response/context budgets, model pricing, manual body metrics, check-in, goals, activity feedback, interval editing and review alignment.

## Editing behavior

- An empty or incomplete intermediate value stays visible while editing. For example, replacing 8 with 2 first shows an empty field and then 2; it does not insert 1 and turn the next keystroke into 12.
- Valid in-range values reach the parent state immediately, so tapping an action with the field still focused uses the entered value. The local text draft keeps the caret and decimal separator stable across parent renders.
- Numeric bounds apply when leaving the field or pressing Enter. A blank required field restores its last accepted value. Optional fields can remain blank; zero stays a separate explicit value. Non-numeric text restores the last accepted value and is not sent to the application.
- Decimal fields accept `75,5` and `75.5`; requests use the numeric value `75.5`. Integers remain integers. Keyboard arrows use the configured increment without imposing a step multiple on a manually typed value, so a context field can accept 8,000 even with 1,024-token arrow increments.
- The control uses a text draft with a numeric/decimal mobile keyboard, spinbutton semantics, arrow controls and custom validity for incomplete/out-of-range drafts. Backend validation remains in place.
- External presets, model settings, resets and loaded profile values still update the field. These controls do not add network writes or change existing save actions.

## Relation to invalid AI plans

Previously several fields immediately converted and clamped every keystroke. In a required field, deleting the old value inserted the minimum and made subsequent typing unreliable. That could submit an unintended response budget, context size or plan length. It does not prove that this caused a particular invalid IONOS/Qwen/GPT response; the exact model response and effective budgets are needed to diagnose that.

An invalid structured plan still fails schema validation. The UI now states that generation stopped, clears old preparation status and suggests checking the model, prompt and response budget. It no longer always claims an automatic retry, since that retry depends on the available per-call budget.

## Validation and update

`npm run test:numbers` covers replacement sequences, bounds, integer/decimal parsing, comma normalization, optional clearing, zero and invalid input. Browser checks exercise real keystrokes and caret edits, mobile layouts, the exact outgoing plan/Coach/admin/profile/body payloads and failed-job status. AI endpoints are simulated; these tests do not make paid IONOS model calls or reproduce the original person's private response. Chromium mobile emulation is not a physical iPhone/Safari test.

There is no new migration or runtime dependency. The update package overlays alpha.61. Apply it using the normal updater and rebuild/restart the web service; the existing API/worker code is compatible. If upgrading from an earlier release using the full package, retain its usual migration and service restart workflow.
