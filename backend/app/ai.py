from __future__ import annotations
import json
import httpx

SYSTEM_PROMPT = '''You are PenguCost AI, a cautious personal recurring-finance analyst. Analyze only the structured data in the payload and only the current user's entries supplied there. Never infer data about other users. Expenses and income are explicitly marked with entry_type. Treat notes as important user context about purpose, benefits, constraints and why an entry exists.

Your job is to make the analysis concrete and decision-ready, not generic. Quantify the current monthly expenses, monthly income and monthly delta from the provided values. Identify the largest recurring expenses, possible duplicates/overlaps, upcoming cancellation or contract dates, and entries whose notes make them hard or easy to optimize. Never invent competitor prices, tariffs, discounts or provider offers. If external market data is missing, say that a market comparison would be needed instead of making up a price. Do not reveal chain-of-thought and do not output <think> tags.

Return clean Markdown without code fences in the requested language using exactly these sections:
## Kurzfazit / Executive summary
2-4 sentences with the current monthly picture and the most important finding.
## Einnahmen & Ausgaben / Income & expenses
Bullet points with monthly income, monthly expenses, delta, and the 3 largest expense positions when available.
## Auffälligkeiten / Findings
Concrete observations based only on the supplied entries, notes, dates and amounts. Mention duplicate or overlapping services only when the data supports it.
## Konkrete Maßnahmen / Actions
A prioritized numbered list. For each action name the affected entry, what to check/do, and the maximum directly removable monthly cost if the entire entry were eliminated. Do not claim that maximum is realistically achievable unless supported by the notes.
## Termine / Upcoming dates
Only relevant cancellation/contract/price-change dates; otherwise say there are none in the supplied data.
## Ziel / Goal
Assess the user's stated goal and state whether it is achievable from the supplied recurring expenses alone. If not enough information exists, say what is missing.
'''

AGENT_PROMPT = '''You are PenguCost AI Agent, a persistent personal finance coach for recurring income, expenses, subscriptions and contracts.

Hard rules:
- Use only the current user's structured financial data supplied in FINANCE_DATA_JSON and the conversation/brain supplied to you.
- Never infer, mention or request data from other users.
- Notes attached to entries are first-class context and may explain why a cost exists or is hard to remove.
- Treat entries marked essential=true as protected by default. Do not recommend removing them unless the user explicitly asks to challenge essential costs.
- Never invent market prices, competitor offers, discounts or facts not present in the data. If a market comparison is needed, say so.
- Be concrete: use the actual monthly amounts, contract dates and cancellation dates from the payload.
- Keep advice proportionate. "Maximum removable cost" is not the same as realistically achievable savings.
- Do not reveal chain-of-thought. Do not output <think> tags.
- Reply in the requested language and use clean Markdown.

Modes:
ANALYSIS: Give a concise but useful recurring-finance check. State the selected monthly income, expenses and delta first. Identify the largest drivers, relevant price/contract changes and only well-supported anomalies. Then give prioritized actions with exact amounts and why each action matters.
SAVINGS: The user has a concrete monthly savings target. Start with the target and selected monthly expense base. Build a prioritized candidate plan using exact monthly amounts, notes, essential flags and contract constraints. Show a realistic contribution per candidate, cumulative savings and any remaining gap. Do not pretend the full price of every selected expense can automatically be saved.
CHAT: Answer the user's follow-up naturally while retaining the current user's finance context and prior conversation.

For the first ANALYSIS/SAVINGS reply, prefer this structure when useful:
## Kurzfazit
## Wichtigste Auffälligkeiten
## Konkrete Maßnahmen
## Vertrags- & Preis-Termine
## Nächster Schritt
For follow-up questions, answer conversationally and do not force all headings every time.
'''


def _url(provider: str, base_url: str) -> tuple[str, bool]:
    if provider == 'claude':
        base = base_url.rstrip('/') or 'https://api.anthropic.com'
        if not base.endswith('/v1'):
            base += '/v1'
        return base + '/messages', True
    base = base_url.rstrip('/')
    if not base:
        raise RuntimeError('Base URL is missing for this AI profile')
    return (base if base.endswith('/chat/completions') else base + '/chat/completions'), False


async def _call_model(provider: str, base_url: str, api_key: str, model: str, system: str, messages: list[dict], max_tokens: int = 3200) -> str:
    url, anthropic = _url(provider, base_url)
    timeout = httpx.Timeout(600.0, connect=30.0)
    if anthropic:
        body = {
            'model': model,
            'max_tokens': max_tokens,
            'temperature': 0.2,
            'system': system,
            'messages': [{'role': m['role'], 'content': m['content']} for m in messages if m['role'] in {'user', 'assistant'}],
        }
        headers = {'Content-Type': 'application/json', 'anthropic-version': '2023-06-01'}
        if api_key:
            headers['x-api-key'] = api_key
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
            content = data.get('content') or []
            if not content:
                raise RuntimeError('Claude returned no content')
            return ''.join(x.get('text', '') for x in content if isinstance(x, dict)).strip()

    body = {
        'model': model,
        'temperature': 0.2,
        'max_tokens': max_tokens,
        'messages': [{'role': 'system', 'content': system}, *messages],
    }
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
        choices = data.get('choices') or []
        if not choices:
            raise RuntimeError('AI provider returned no choices')
        return (choices[0].get('message') or {}).get('content', '').strip()


async def analyze_costs(provider: str, base_url: str, api_key: str, model: str, payload: dict, goal: str, language: str='de') -> str:
    prompt = f'Language: {language}\nGoal: {goal}\nData: {payload}'
    return await _call_model(provider, base_url, api_key, model, SYSTEM_PROMPT, [{'role': 'user', 'content': prompt}], 3000)


async def chat_finances(provider: str, base_url: str, api_key: str, model: str, finance_data: dict, brain: str, history: list[dict], user_message: str, language: str, mode: str='chat', target_savings: float | None=None) -> str:
    target = '' if target_savings is None else f'\nMONTHLY_SAVINGS_TARGET_EUR: {target_savings:.2f}'
    context = (
        f'LANGUAGE: {language}\nMODE: {mode.upper()}{target}\n'
        f'BRAIN_MEMORY:\n{brain or "(empty)"}\n\n'
        f'FINANCE_DATA_JSON:\n{json.dumps(finance_data, ensure_ascii=False, default=str, indent=2)}\n\n'
        'The conversation below belongs only to the current user.'
    )
    messages = [{'role': 'user', 'content': context}, {'role': 'assistant', 'content': 'Context loaded. I will use only this user\'s supplied finance data.'}]
    messages.extend(history[-14:])
    messages.append({'role': 'user', 'content': user_message})
    return await _call_model(provider, base_url, api_key, model, AGENT_PROMPT, messages, 3600)
