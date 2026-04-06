import os
try:
    from openai import OpenAI as _OpenAI
    _openai_available = True
except ImportError:
    _OpenAI = None
    _openai_available = False

_client = _OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if _openai_available else None

def get_llm_trade(context):
    if not _openai_available or _client is None:
        return '{"action": "NO_TRADE", "confidence": 0, "reason": "openai not installed", "sl": null, "tp": null}'
    prompt = f"""
    You are a professional institutional trader.

    Analyze:
    {context}

    Output JSON:
    {{
        \"action\": \"BUY or SELL or NO_TRADE\",
        \"confidence\": 0-100,
        \"reason\": \"short reasoning\",
        \"sl\": value,
        \"tp\": value
    }}
    """

    res = _client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return res.choices[0].message.content
