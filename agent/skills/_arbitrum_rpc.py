"""
Arbitrum JSON-RPC utility (tx/receipt/log scan).

Designed to be called by OpenClaw's exec tool with a single string argument.
The argument can be either:
  1) a tx hash (0x...) -> returns a tx+receipt "bundle"
  2) a JSON object string -> structured requests (chain_id, tx_bundle, get_logs, scan_logs)

Env:
  - ARBITRUM_RPC_URL: defaults to https://arb1.arbitrum.io/rpc
  - RPC_HTTP_TIMEOUT_S: request timeout (default 20)
  - RPC_RETRIES: retries on transient failures (default 2)
  - RPC_LOG_CHUNK_SIZE: block span per eth_getLogs call when scanning (default 2000)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import requests


TX_HASH_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


@dataclass(frozen=True)
class RpcConfig:
    url: str
    timeout_s: int
    retries: int
    log_chunk_size: int


def _get_config(override_url: Optional[str] = None) -> RpcConfig:
    url = (override_url or os.getenv("ARBITRUM_RPC_URL") or "https://arb1.arbitrum.io/rpc").strip()
    return RpcConfig(
        url=url,
        timeout_s=_env_int("RPC_HTTP_TIMEOUT_S", 20),
        retries=_env_int("RPC_RETRIES", 2),
        log_chunk_size=max(1, _env_int("RPC_LOG_CHUNK_SIZE", 2000)),
    )


def _rpc_call(cfg: RpcConfig, method: str, params: list) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last_err: Optional[str] = None
    for attempt in range(cfg.retries + 1):
        try:
            r = requests.post(cfg.url, json=payload, timeout=cfg.timeout_s)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("error"):
                raise RuntimeError(f"rpc_error: {data['error']}")
            return data["result"]
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < cfg.retries:
                time.sleep(min(2 ** attempt, 4))
                continue
            raise RuntimeError(last_err)


def _parse_block_tag(v: Any) -> Union[str, int]:
    """
    Accepts:
      - "latest" / "earliest" / "pending"
      - decimal int / string
      - hex string like "0x10d4f"
    Returns:
      - RPC block tag string (hex like "0x...") or "latest"/etc
    """
    if v is None:
        return "latest"
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("latest", "earliest", "pending"):
            return s
        if s.startswith("0x"):
            return s
        # decimal string
        try:
            n = int(s)
            return hex(n)
        except Exception:
            return "latest"
    if isinstance(v, int):
        return hex(v)
    return "latest"


def get_chain_id(cfg: RpcConfig) -> int:
    res = _rpc_call(cfg, "eth_chainId", [])
    return int(res, 16) if isinstance(res, str) and res.startswith("0x") else int(res)


def get_block_number(cfg: RpcConfig) -> int:
    res = _rpc_call(cfg, "eth_blockNumber", [])
    return int(res, 16)


def get_tx(cfg: RpcConfig, tx_hash: str) -> Optional[dict]:
    return _rpc_call(cfg, "eth_getTransactionByHash", [tx_hash])


def get_receipt(cfg: RpcConfig, tx_hash: str) -> Optional[dict]:
    return _rpc_call(cfg, "eth_getTransactionReceipt", [tx_hash])


def get_logs(cfg: RpcConfig, filt: dict) -> List[dict]:
    return _rpc_call(cfg, "eth_getLogs", [filt]) or []


def tx_bundle(cfg: RpcConfig, tx_hash: str) -> dict:
    tx = get_tx(cfg, tx_hash)
    receipt = get_receipt(cfg, tx_hash)
    logs = (receipt or {}).get("logs", []) if isinstance(receipt, dict) else []
    status = (receipt or {}).get("status") if isinstance(receipt, dict) else None
    return {
        "rpc_url": cfg.url,
        "tx_hash": tx_hash,
        "chain_id": get_chain_id(cfg),
        "tx": tx,
        "receipt": receipt,
        "status": status,
        "logs": logs,
    }


def scan_logs(
    cfg: RpcConfig,
    address: Optional[Union[str, List[str]]],
    topics: Optional[List[Optional[Union[str, List[str]]]]],
    from_block: Any,
    to_block: Any,
) -> dict:
    fb = _parse_block_tag(from_block)
    tb = _parse_block_tag(to_block)

    if fb in ("latest", "pending") or tb in ("earliest",):
        raise RuntimeError("scan_logs requires concrete block numbers (use get_logs for tags)")

    fb_i = int(str(fb), 16) if isinstance(fb, str) and fb.startswith("0x") else int(fb)
    tb_i = int(str(tb), 16) if isinstance(tb, str) and tb.startswith("0x") else int(tb)
    if tb_i < fb_i:
        fb_i, tb_i = tb_i, fb_i

    chunk = cfg.log_chunk_size
    all_logs: List[dict] = []
    ranges: List[Tuple[int, int]] = []
    for start in range(fb_i, tb_i + 1, chunk):
        end = min(start + chunk - 1, tb_i)
        ranges.append((start, end))

    for start, end in ranges:
        filt: Dict[str, Any] = {
            "fromBlock": hex(start),
            "toBlock": hex(end),
        }
        if address:
            filt["address"] = address
        if topics is not None:
            filt["topics"] = topics
        logs = get_logs(cfg, filt)
        all_logs.extend(logs)

    return {
        "rpc_url": cfg.url,
        "chain_id": get_chain_id(cfg),
        "address": address,
        "topics": topics,
        "from_block": fb_i,
        "to_block": tb_i,
        "chunk_size": chunk,
        "chunks": len(ranges),
        "log_count": len(all_logs),
        "logs": all_logs,
    }


def _parse_input(argv: List[str]) -> Tuple[str, Dict[str, Any]]:
    raw = " ".join(argv[1:]).strip() if len(argv) > 1 else ""
    if TX_HASH_RE.match(raw):
        return "tx_hash", {"tx_hash": raw}
    # PowerShell / command-runner quoting can be lossy for JSON-with-quotes.
    # Support simple non-JSON shorthands to make invocation robust.
    lowered = raw.lower()
    if lowered in ("chain_id", "chainid"):
        return "json", {"action": "chain_id"}
    if lowered in ("block_number", "blocknumber", "block"):
        return "json", {"action": "block_number"}
    if lowered.startswith("tx_bundle ") or lowered.startswith("bundle "):
        parts = raw.split()
        if len(parts) >= 2 and TX_HASH_RE.match(parts[1]):
            return "json", {"action": "tx_bundle", "tx_hash": parts[1]}
    if lowered.startswith("scan_logs "):
        # scan_logs <from_block> <to_block> <address?> <topic0?>
        parts = raw.split()
        from_block = parts[1] if len(parts) > 1 else None
        to_block = parts[2] if len(parts) > 2 else None
        address = parts[3] if len(parts) > 3 and parts[3].startswith("0x") else None
        topic0 = parts[4] if len(parts) > 4 and parts[4].startswith("0x") else None
        topics = [topic0] if topic0 else None
        return "json", {"action": "scan_logs", "from_block": from_block, "to_block": to_block, "address": address, "topics": topics}
    if lowered.startswith("get_logs "):
        # get_logs <from_block|tag> <to_block|tag> <address?> <topic0?>
        parts = raw.split()
        from_block = parts[1] if len(parts) > 1 else None
        to_block = parts[2] if len(parts) > 2 else None
        address = parts[3] if len(parts) > 3 and parts[3].startswith("0x") else None
        topic0 = parts[4] if len(parts) > 4 and parts[4].startswith("0x") else None
        topics = [topic0] if topic0 else None
        return "json", {"action": "get_logs", "from_block": from_block, "to_block": to_block, "address": address, "topics": topics}
    if raw.startswith("{") and raw.endswith("}"):
        try:
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                raise ValueError("json input must be an object")
            return "json", obj
        except Exception as e:
            return "error", {"error": f"invalid_json: {type(e).__name__}: {e}", "raw": raw}
    if raw:
        return "error", {"error": "unrecognized_input", "raw": raw}
    return "error", {"error": "missing_input"}


def main() -> None:
    kind, payload = _parse_input(sys.argv)
    if kind == "error":
        print(json.dumps(payload, indent=2))
        raise SystemExit(1)

    try:
        if kind == "tx_hash":
            cfg = _get_config()
            out = tx_bundle(cfg, payload["tx_hash"])
            print(json.dumps(out, indent=2))
            return

        action = str(payload.get("action", "tx_bundle")).strip().lower()
        cfg = _get_config(override_url=payload.get("rpc_url"))

        if action in ("chain_id", "chainid"):
            print(json.dumps({"rpc_url": cfg.url, "chain_id": get_chain_id(cfg)}, indent=2))
            return

        if action in ("block_number", "blocknumber"):
            print(json.dumps({"rpc_url": cfg.url, "block_number": get_block_number(cfg)}, indent=2))
            return

        if action in ("tx_bundle", "bundle"):
            tx_hash = payload.get("tx_hash") or payload.get("txHash") or payload.get("hash")
            if not isinstance(tx_hash, str) or not TX_HASH_RE.match(tx_hash):
                raise RuntimeError("tx_bundle requires tx_hash (0x...)")
            print(json.dumps(tx_bundle(cfg, tx_hash), indent=2))
            return

        if action in ("get_logs", "logs"):
            filt: Dict[str, Any] = {}
            address = payload.get("address")
            topics = payload.get("topics")
            if address:
                filt["address"] = address
            if topics is not None:
                filt["topics"] = topics
            filt["fromBlock"] = _parse_block_tag(payload.get("from_block") or payload.get("fromBlock"))
            filt["toBlock"] = _parse_block_tag(payload.get("to_block") or payload.get("toBlock"))
            logs = get_logs(cfg, filt)
            print(json.dumps(
                {
                    "rpc_url": cfg.url,
                    "chain_id": get_chain_id(cfg),
                    "filter": filt,
                    "log_count": len(logs),
                    "logs": logs,
                },
                indent=2
            ))
            return

        if action in ("scan_logs", "scan"):
            address = payload.get("address")
            topics = payload.get("topics")
            from_block = payload.get("from_block") or payload.get("fromBlock")
            to_block = payload.get("to_block") or payload.get("toBlock")
            print(json.dumps(
                scan_logs(cfg, address=address, topics=topics, from_block=from_block, to_block=to_block),
                indent=2
            ))
            return

        raise RuntimeError(f"unknown_action: {action}")

    except Exception as e:
        print(json.dumps(
            {
                "error": str(e),
                "hint": "Pass a tx hash, or JSON like "
                        "{\"action\":\"tx_bundle\",\"tx_hash\":\"0x...\"} / "
                        "{\"action\":\"scan_logs\",\"address\":\"0x...\",\"topics\":[\"0x...\"],\"from_block\":123,\"to_block\":456}",
            },
            indent=2
        ))
        raise SystemExit(1)


if __name__ == "__main__":
    main()

