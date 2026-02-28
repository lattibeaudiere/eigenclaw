"""
CoinGecko simple price fetcher for USD valuation.

Input forms:
  1) "GHO,USDC,WETH"
  2) '{"symbols":["GHO","USDC"],"vs_currency":"usd"}'
  3) '{"ids":["gho","usd-coin"],"vs_currency":"usd"}'

Env:
  - COINGECKO_BASE_URL (default: https://api.coingecko.com/api/v3)
  - COINGECKO_API_KEY (optional; sent as x-cg-pro-api-key first, then demo fallback)
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Tuple

import requests


SYMBOL_TO_ID = {
    "ETH": "ethereum",
    "WETH": "weth",
    "WBTC": "wrapped-bitcoin",
    "BTC": "bitcoin",
    "USDC": "usd-coin",
    "USDT": "tether",
    "DAI": "dai",
    "ARB": "arbitrum",
    "LINK": "chainlink",
    "AAVE": "aave",
    "GHO": "gho",
}


def _parse_input(argv: List[str]) -> Dict[str, Any]:
    raw = " ".join(argv[1:]).strip() if len(argv) > 1 else ""
    if not raw:
        return {"symbols": ["GHO", "USDC", "WETH"], "vs_currency": "usd"}
    if raw.startswith("{") and raw.endswith("}"):
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError("JSON input must be an object")
        return obj
    symbols = [p.strip().upper() for p in raw.split(",") if p.strip()]
    return {"symbols": symbols, "vs_currency": "usd"}


def _resolve_ids(obj: Dict[str, Any]) -> Tuple[List[str], Dict[str, str], List[str]]:
    ids = obj.get("ids")
    if isinstance(ids, list) and ids:
        clean = [str(x).strip().lower() for x in ids if str(x).strip()]
        return clean, {}, []

    symbols = obj.get("symbols")
    if not isinstance(symbols, list):
        symbols = []
    symbol_to_id: Dict[str, str] = {}
    missing: List[str] = []
    for s in symbols:
        sym = str(s).strip().upper()
        if not sym:
            continue
        cid = SYMBOL_TO_ID.get(sym)
        if cid:
            symbol_to_id[sym] = cid
        else:
            missing.append(sym)
    return list(symbol_to_id.values()), symbol_to_id, missing


def _fetch_simple_price(base_url: str, ids: List[str], vs_currency: str, api_key: str) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/simple/price"
    params = {
        "ids": ",".join(ids),
        "vs_currencies": vs_currency,
        "include_market_cap": "true",
        "include_24hr_vol": "true",
        "include_24hr_change": "true",
        "include_last_updated_at": "true",
    }
    headers = {"Accept": "application/json"}

    attempts = []
    if api_key:
        attempts.append({"x-cg-pro-api-key": api_key})
        attempts.append({"x-cg-demo-api-key": api_key})
    attempts.append({})

    last_err = "unknown error"
    for auth_headers in attempts:
        try:
            merged = headers | auth_headers
            r = requests.get(url, params=params, headers=merged, timeout=20)
            if r.status_code >= 400:
                last_err = f"HTTP {r.status_code}: {r.text[:220]}"
                continue
            return r.json()
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            continue
    raise RuntimeError(last_err)


def main() -> None:
    try:
        req = _parse_input(sys.argv)
        vs_currency = str(req.get("vs_currency", "usd")).lower()
        ids, symbol_to_id, missing_symbols = _resolve_ids(req)
        if not ids:
            raise RuntimeError("no valid token ids/symbols provided")

        base_url = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")
        api_key = os.getenv("COINGECKO_API_KEY", "").strip()
        raw = _fetch_simple_price(base_url, ids, vs_currency, api_key)

        out_prices = {}
        id_to_symbol = {v: k for k, v in symbol_to_id.items()}
        for cid in ids:
            if cid not in raw:
                continue
            label = id_to_symbol.get(cid, cid)
            out_prices[label] = raw[cid]

        out = {
            "source": "coingecko",
            "endpoint": "/simple/price",
            "vs_currency": vs_currency,
            "prices": out_prices,
            "missing_symbols": missing_symbols,
            "resolved_ids": ids,
        }
        print(json.dumps(out, indent=2))
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()

