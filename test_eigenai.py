"""
Quick smoke-test for EigenAI verifiable LLM inference.
Run this first to confirm your API key and endpoint are working.

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # fill in EIGENCLOUD_API_KEY
    python test_eigenai.py
"""

import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("EIGENCLOUD_API_KEY")
BASE_URL = os.getenv("EIGENAI_BASE_URL", "https://eigenai.eigencloud.xyz/v1")
MODEL    = os.getenv("EIGENAI_MODEL", "gpt-oss-120b-f16")

if not API_KEY or API_KEY == "your_api_key_here":
    raise SystemExit(
        "ERROR: Set EIGENCLOUD_API_KEY in your .env file.\n"
        "  1. Copy .env.example → .env\n"
        "  2. Fill in your key from the EigenCloud dashboard\n"
        "     or run: ecloud auth generate --store"
    )

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

# Representative sample transactions to test the classifier
SAMPLE_TXS = [
    {
        "label": "Aave delegated supply",
        "user_content": (
            "Calldata starts with redeemDelegations selector. "
            "Logs: Aave Mint 128.569 aArbUSDCn from 0x000...000 to beneficiary 0xabc..., "
            "USDC Transfer 127.929 USDC → aArbUSDCn contract."
        ),
    },
    {
        "label": "Odos swap",
        "user_content": (
            "Calldata selector: 0x83bd37f9 (Odos swap). "
            "Logs: WETH Transfer 0.5 → OdosRouter, USDC Transfer 1234.56 → msg.sender. "
            "No Aave events."
        ),
    },
    {
        "label": "Aave borrow",
        "user_content": (
            "Calldata: borrow(address,uint256,uint256,uint16,address). "
            "Logs: Aave Borrow event — asset=USDC, amount=500, interestRateMode=2 (variable), "
            "onBehalfOf=msg.sender."
        ),
    },
]

client = OpenAI(
    base_url=BASE_URL,
    api_key=API_KEY,
    default_headers={"x-api-key": API_KEY},
)

print(f"EigenAI endpoint : {BASE_URL}")
print(f"Model            : {MODEL}")
print("-" * 60)

for tx in SAMPLE_TXS:
    print(f"\n[{tx['label']}]")
    print(f"Input: {tx['user_content'][:80]}...")

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": tx["user_content"]},
        ],
        temperature=0.0,
        max_tokens=400,
    )

    raw = response.choices[0].message.content.strip()

    # Validate it's actually JSON before printing
    try:
        parsed = json.loads(raw)
        print(json.dumps(parsed, indent=2))
    except json.JSONDecodeError:
        print("WARNING: model returned non-JSON output:")
        print(raw)

print("\nDone. If all three printed valid JSON, your EigenAI setup is working.")
