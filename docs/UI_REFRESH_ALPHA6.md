# PenguCoach UI Refresh — 0.1.0-alpha.6

`0.1.0-alpha.6` introduces the first full visual system for PenguCoach. The goal is a bright, calm health-and-training interface with better hierarchy, readability and responsive behavior while preserving the existing data and AI workflows.

## Visual direction

- light health-first palette with mint/teal accents and restrained supporting colors
- persistent desktop sidebar with grouped navigation
- compact sticky context header and mobile bottom navigation
- larger whitespace, softer borders and subtle shadows instead of dense card chrome
- consistent page headings, pills, form controls, tables and status surfaces
- modern login experience that explains the local-first product at a glance

## Dashboard

The Today page is redesigned around three priorities:

1. current training/recovery context
2. fast access to the AI Coach and recent activities
3. readable daily Garmin metrics and a longer-term resting-HR trend

Health cards use restrained semantic accent tones while keeping text contrast high.

## Health

The Health page now uses a consistent period selector, compact metric cards, larger trend surfaces and a dedicated data-coverage summary. Missing Garmin values remain missing; the visual redesign does not invent or interpolate health facts.

## Activities

The activity history now includes:

- search by activity name or sport
- compact activity summary counters
- sport-aware badges
- clearer distance/duration/HR hierarchy
- visible FIT processing status
- responsive layouts that retain the activity name and status on smaller screens

The existing Activity Detail v2 analytics remain intact and receive the same light visual treatment.

## Coach and AI Studio

Existing alpha.5 background jobs, model routing, context-window controls and token budgets are unchanged functionally. The alpha.6 design system makes these controls calmer and more consistent with the rest of the product.

## Responsive behavior

- desktop: persistent sidebar and full content width
- tablet: sidebar becomes a mobile navigation dock
- mobile: five primary destinations remain one tap away at the bottom of the screen
- dense activity tables remain horizontally scrollable rather than truncating analytical data
