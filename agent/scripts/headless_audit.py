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
    explorer_url = f"{base_url}/api/explorer/events?limit={limit}"

    try:
        explorer = _fetch_json(explorer_url, headers=headers, timeout_s=timeout_s)
    except Exception as e:
        _append_md(
            audit_log,
            f"\n## {started} — Headless audit (FAILED)\n\n- **error**: `{type(e).__name__}: {e}`\n",
        )
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

    tx_hashes = []
    for it in items:
        if not isinstance(it, dict):
            continue
        h = _extract_hash(it)
        if h:
            tx_hashes.append(h)
        if len(tx_hashes) >= max_txs:
            break

    entry_lines = [
        f"\n## {started} — Headless audit\n",
        f"- **base**: `{base_url}`\n",
        f"- **explorer**: `{explorer_url}`\n",
        f"- **txs_sampled**: {len(tx_hashes)}\n",
    ]

    for h in tx_hashes:
        tx_url = f"{base_url}/api/tx/{h}"
        try:
            tx = _fetch_json(tx_url, headers=headers, timeout_s=timeout_s)
        except Exception as e:
            entry_lines.append(f"\n### {h}\n- **fetch_failed**: `{type(e).__name__}: {e}`\n")
            continue

        action_type = None
        for k in ("action_type", "actionType", "type"):
            v = tx.get(k) if isinstance(tx, dict) else None
            if isinstance(v, str):
                action_type = v
                break

        outcome_asset = None
        for k in ("outcome_asset", "outcomeAsset", "reserve"):
            v = tx.get(k) if isinstance(tx, dict) else None
            if isinstance(v, str) and v.startswith("0x"):
                outcome_asset = v
                break

        asset_symbol = None
        for k in ("asset_symbol", "assetSymbol", "symbol"):
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

        entry_lines.append(f"\n### {h}\n")
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
            "explorer_url": explorer_url,
            "tx_hashes": tx_hashes,
        }
        (workspace / "audit_snapshots").mkdir(parents=True, exist_ok=True)
        (workspace / "audit_snapshots" / f"{day}-{started.replace(':', '')}.json").write_text(
            json.dumps(snapshot, indent=2), encoding="utf-8"
        )

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

