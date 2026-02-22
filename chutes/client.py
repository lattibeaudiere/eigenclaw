"""
Chutes inference client — used by server.py and label_txs.py.

Calls the deployed Chutes TEE endpoint (primary) with automatic fallback
to EigenAI if Chutes is unreachable or not yet configured.

Priority:
  1. Chutes TEE endpoint  (CHUTES_ENDPOINT + CHUTES_API_KEY set)
  2. EigenAI endpoint     (EIGENCLOUD_API_KEY set)
  3. Raise RuntimeError   (neither configured)
"""

import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ── Chutes config ─────────────────────────────────────────────────────────────
CHUTES_ENDPOINT = os.getenv("CHUTES_ENDPOINT", "")
CHUTES_API_KEY  = os.getenv("CHUTES_API_KEY", "")
CHUTES_MODEL    = os.getenv("CHUTES_MODEL", "Llama-3.2-11B-Vision-Instruct")

# ── EigenAI fallback config ───────────────────────────────────────────────────
EIGENAI_BASE_URL = os.getenv("EIGENAI_BASE_URL", "https://eigenai.eigencloud.xyz/v1")
EIGENAI_API_KEY  = os.getenv("EIGENCLOUD_API_KEY", "")
EIGENAI_MODEL    = os.getenv("EIGENAI_MODEL", "gpt-oss-120b-f16")

SYSTEM_PROMPT = """\
You are a precise DeFi transaction intent classifier.
Given a calldata snippet and key event logs, output ONLY valid JSON with exactly these fields:
{
  "action_type": "<verb in SCREAMING_SNAKE_CASE>",
  "protocol":    "<protocol name>",
  "token_in":    "<symbol or null>",
  "amount_in":   <float or null>,
  "token_out":   "<symbol or null>",
  "amount_out":  <float or null>,
  "confidence":  <0.0–1.0>,
  "reason":      "<one-sentence explanation>"
}
Rules:
- Prioritise protocol events (e.g. Aave Mint/Supply) over function selectors.
- If redeemDelegations is present in calldata, use DELEGATED_SUPPLY.
- Never include extra keys or prose outside the JSON object.\
"""


def _chutes_client() -> tuple[OpenAI, str] | None:
    """Return (client, model) for Chutes if configured, else None."""
    if CHUTES_ENDPOINT and CHUTES_API_KEY:
        client = OpenAI(
            base_url=f"{CHUTES_ENDPOINT.rstrip('/')}/v1",
            api_key=CHUTES_API_KEY,
        )
        return client, CHUTES_MODEL
    return None


def _eigenai_client() -> tuple[OpenAI, str] | None:
    """Return (client, model) for EigenAI if configured, else None."""
    if EIGENAI_API_KEY:
        client = OpenAI(
            base_url=EIGENAI_BASE_URL,
            api_key=EIGENAI_API_KEY,
            default_headers={"x-api-key": EIGENAI_API_KEY},
        )
        return client, EIGENAI_MODEL
    return None


def active_backend() -> str:
    """Return which inference backend is currently active."""
    if CHUTES_ENDPOINT and CHUTES_API_KEY:
        return f"Chutes TEE ({CHUTES_ENDPOINT})"
    if EIGENAI_API_KEY:
        return f"EigenAI ({EIGENAI_BASE_URL})"
    return "none (not configured)"


def classify(description: str) -> dict:
    """
    Classify a DeFi tx description using the best available TEE backend.
    Returns a parsed JSON dict with action_type, protocol, amounts, confidence, reason.
    """
    pair = _chutes_client() or _eigenai_client()
    if not pair:
        raise RuntimeError(
            "No inference backend configured. "
            "Set CHUTES_API_KEY + CHUTES_ENDPOINT or EIGENCLOUD_API_KEY in .env"
        )

    client, model = pair

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": description},
        ],
        temperature=0.0,
        max_tokens=400,
    )

    raw = response.choices[0].message.content.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "non_json_response", "raw": raw}
