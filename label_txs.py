"""
Batch DeFi transaction labeler using EigenAI verifiable inference.

Input : a JSON file — list of tx objects with at least a "description" field
        (or "calldata" + "logs" fields — see TX_DESCRIPTION_FIELD below).
Output: same objects with "label" dict injected, written to output/labeled_txs.json

Usage:
    python label_txs.py --input data/sample_txs.json
    python label_txs.py --input data/sample_txs.json --concurrency 4 --testnet
"""

import os
import json
import time
import argparse
import concurrent.futures
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MAINNET_URL = "https://eigenai.eigencloud.xyz/v1"
TESTNET_URL = "https://eigenai-sepolia.eigencloud.xyz/v1"

API_KEY = os.getenv("EIGENCLOUD_API_KEY", "")
MODEL   = os.getenv("EIGENAI_MODEL", "gpt-oss-120b-f16")

# Which field in each tx object contains the natural-language description.
# Override with --field if your data uses a different key.
TX_DESCRIPTION_FIELD = "description"

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_client(testnet: bool) -> OpenAI:
    base_url = TESTNET_URL if testnet else MAINNET_URL
    return OpenAI(
        base_url=base_url,
        api_key=API_KEY,
        default_headers={"x-api-key": API_KEY},
    )


def classify_tx(client: OpenAI, tx: dict, field: str, retries: int = 3) -> dict:
    """Call EigenAI and return the tx dict with a 'label' key added."""
    description = tx.get(field) or tx.get("calldata", "") + " " + str(tx.get("logs", ""))
    if not description.strip():
        tx["label"] = {"error": "no_description_found"}
        return tx

    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": description},
                ],
                temperature=0.0,
                max_tokens=400,
            )
            raw = response.choices[0].message.content.strip()
            tx["label"] = json.loads(raw)
            return tx
        except json.JSONDecodeError:
            tx["label"] = {"error": "non_json_response", "raw": raw}
            return tx
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)   # exponential back-off: 1s, 2s, 4s
            else:
                tx["label"] = {"error": str(exc)}
    return tx


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Batch-label DeFi txs via EigenAI.")
    parser.add_argument("--input",       required=True,        help="Path to input JSON file")
    parser.add_argument("--output",      default="output/labeled_txs.json")
    parser.add_argument("--field",       default=TX_DESCRIPTION_FIELD,
                        help="Key in each tx object that holds the text description")
    parser.add_argument("--concurrency", type=int, default=2,
                        help="Parallel requests (keep low to stay within rate limits)")
    parser.add_argument("--testnet",     action="store_true",
                        help="Use Sepolia testnet endpoint (cheaper for experimentation)")
    args = parser.parse_args()

    if not API_KEY or API_KEY == "your_api_key_here":
        raise SystemExit(
            "ERROR: Set EIGENCLOUD_API_KEY in your .env file.\n"
            "  Copy .env.example → .env and fill in your key."
        )

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"ERROR: Input file not found: {input_path}")

    with open(input_path) as f:
        txs = json.load(f)

    if not isinstance(txs, list):
        raise SystemExit("ERROR: Input JSON must be a list of transaction objects.")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    client = build_client(testnet=args.testnet)
    endpoint = TESTNET_URL if args.testnet else MAINNET_URL
    print(f"Endpoint    : {endpoint}")
    print(f"Model       : {MODEL}")
    print(f"Input txs   : {len(txs)}")
    print(f"Concurrency : {args.concurrency}")
    print(f"Output      : {output_path}")
    print("-" * 60)

    labeled = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(classify_tx, client, tx, args.field): i
            for i, tx in enumerate(txs)
        }
        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            result = future.result()
            action = result.get("label", {}).get("action_type", "ERROR")
            print(f"  [{idx+1:>4}/{len(txs)}] {action}")
            labeled.append((idx, result))

    # Restore original order
    labeled.sort(key=lambda x: x[0])
    ordered = [tx for _, tx in labeled]

    with open(output_path, "w") as f:
        json.dump(ordered, f, indent=2)

    errors = sum(1 for tx in ordered if "error" in tx.get("label", {}))
    print(f"\nDone. {len(ordered) - errors}/{len(ordered)} labeled successfully → {output_path}")
    if errors:
        print(f"  {errors} errors — check 'label.error' fields in the output file.")


if __name__ == "__main__":
    main()
