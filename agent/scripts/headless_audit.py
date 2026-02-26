import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

import requests


def _workspace_paths() -> Tuple[Path, Path, Path]:
    home = Path.home()
    workspace = home / ".openclaw" / "workspace"
    audit_log = workspace / "AUDIT_LOG.md"
    memory_dir = workspace / "memory"
    return workspace, audit_log, memory_dir


def _append_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _now_iso() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat(timespec="seconds")


def _safe_get(d: Dict[str, Any], *keys: str) -> Optional[Any]:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _iter_strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_strings(v)


def _extract_hash(item: Dict[str, Any]) -> Optional[str]:
    for k in ("ref_tx_hash", "tx_hash", "hash", "txHash"):
        v = item.get(k)
        if isinstance(v, str) and v.startswith("0x") and len(v) >= 10:
            return v
    return None


def _fetch_json(url: str, headers: Dict[str, str], timeout_s: int) -> Any:
    r = requests.get(url, headers=headers, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def run_once() -> int:
    base_url = os.getenv("DEFEYES_BASE_URL", "https://defeyes-api.vercel.app").rstrip("/")
    api_key = os.getenv("DEFEYES_API_KEY", "")
    timeout_s = int(os.getenv("AUDIT_HTTP_TIMEOUT_S", "20"))
    limit = int(os.getenv("AUDIT_EXPLORER_LIMIT", "10"))
    max_txs = int(os.getenv("AUDIT_MAX_TXS", "5"))

    headers: Dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    workspace, audit_log, memory_dir = _workspace_paths()
    memory_dir.mkdir(parents=True, exist_ok=True)
    audit_log.touch(exist_ok=True)

    started = _now_iso()
    # Current API surface: /api/events is canonical. Keep explorer feed as
    # public fallback when no key or paid access is unavailable.
    primary_url = f"{base_url}/api/events?limit={limit}"
    fallback_url = f"{base_url}/api/explorer/events?limit={limit}"
    sample_url = primary_url if api_key else fallback_url

    try:
        explorer = _fetch_json(sample_url, headers=headers, timeout_s=timeout_s)
    except Exception as e:
        # Fallback to public explorer if primary feed is unavailable (e.g. 402)
        try:
            sample_url = fallback_url
            explorer = _fetch_json(sample_url, headers={"Accept": "application/json"}, timeout_s=timeout_s)
        except Exception:
            _append_md(
                audit_log,
                f"\n## {started} — Headless audit (FAILED)\n\n- **error**: `{type(e).__name__}: {e}`\n",
            )
            # Emit a single-line status so we can verify in EigenCloud logs
            print(f"AUDIT_STATUS ts={started} ok=false err={type(e).__name__}")
            return 1

    items: Any = (
        explorer
        if isinstance(explorer, list)
        else _safe_get(explorer, "events")
        or _safe_get(explorer, "data")
        or _safe_get(explorer, "results")
        or []
    )

    if not isinstance(items, list):
        items = []

    sampled: list[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        sampled.append(it)
        if len(sampled) >= max_txs:
            break

    entry_lines = [
        f"\n## {started} — Headless audit\n",
        f"- **base**: `{base_url}`\n",
        f"- **sample_endpoint**: `{sample_url}`\n",
        f"- **txs_sampled**: {len(sampled)}\n",
    ]

    for tx in sampled:
        tx_hash = _extract_hash(tx) or "unknown_tx"

        action_type = None
        for k in ("action_type", "actionType", "type"):
            v = tx.get(k) if isinstance(tx, dict) else None
            if isinstance(v, str):
                action_type = v
                break

        outcome_asset = None
        for k in ("outcome_asset", "outcomeAsset", "reserve", "token_out_address", "tokenOutAddress"):
            v = tx.get(k) if isinstance(tx, dict) else None
            if isinstance(v, str) and v.startswith("0x"):
                outcome_asset = v
                break

        asset_symbol = None
        for k in ("asset_symbol", "assetSymbol", "symbol", "token_out_symbol", "tokenOutSymbol"):
            v = tx.get(k) if isinstance(tx, dict) else None
            if isinstance(v, str):
                asset_symbol = v
                break

        apy_percent = None
        for k in ("apy_percent", "apyPercent", "apy"):
            v = tx.get(k) if isinstance(tx, dict) else None
            if isinstance(v, (int, float, str)):
                apy_percent = v
                break

        strings = list(_iter_strings(tx))
        rdu_count = sum(1 for s in strings if "ReserveDataUpdated" in s)
        supply_borrow_mentioned = any(("Supply" in s or "Borrow" in s) for s in strings)
        multi_reserve_risk = rdu_count > 1 and (action_type or "").upper() not in ("SUPPLY", "BORROW")

        entry_lines.append(f"\n### {tx_hash}\n")
        if action_type:
            entry_lines.append(f"- **action_type**: `{action_type}`\n")
        if asset_symbol:
            entry_lines.append(f"- **asset_symbol**: `{asset_symbol}`\n")
        if outcome_asset:
            entry_lines.append(f"- **outcome_asset**: `{outcome_asset}`\n")
        if apy_percent is not None:
            entry_lines.append(f"- **apy_percent**: `{apy_percent}`\n")

        entry_lines.append(f"- **ReserveDataUpdated_mentions**: {rdu_count}\n")
        entry_lines.append(f"- **Supply/Borrow_mentions**: {str(supply_borrow_mentioned).lower()}\n")

        if rdu_count > 1:
            entry_lines.append(
                "- **note**: multi-reserve transaction detected; APY join must anchor on the Aave outcome reserve.\n"
            )
        if multi_reserve_risk:
            entry_lines.append(
                "- **risk**: possible join-failure (early ReserveDataUpdated may have won). Verify Two-Anchor bundle.\n"
            )
    
    text = "".join(entry_lines)
    _append_md(audit_log, text)

    day = dt.datetime.utcnow().strftime("%Y-%m-%d")
    daily = memory_dir / f"{day}.md"
    _append_md(daily, text)

    # Also persist a compact JSON snapshot for debugging if enabled
    if os.getenv("AUDIT_WRITE_JSON", "false").lower() == "true":
        snapshot = {
            "ts": started,
            "base_url": base_url,
            "sample_url": sample_url,
            "tx_hashes": [(_extract_hash(it) or "unknown_tx") for it in sampled],
        }
        (workspace / "audit_snapshots").mkdir(parents=True, exist_ok=True)
        (workspace / "audit_snapshots" / f"{day}-{started.replace(':', '')}.json").write_text(
            json.dumps(snapshot, indent=2), encoding="utf-8"
        )

    # Emit a single-line status so we can verify in EigenCloud logs
    print(f"AUDIT_STATUS ts={started} ok=true txs={len(sampled)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single audit pass")
    args = parser.parse_args()
    if args.once:
        return run_once()
    return run_once()


if __name__ == "__main__":
    raise SystemExit(main())

