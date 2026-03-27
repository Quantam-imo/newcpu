import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_llm_trade(context):
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

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return res.choices[0].message.content
