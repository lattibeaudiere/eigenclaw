"""
Chutes CSM-1B text-to-speech helper.

Input forms:
  1) plain text
  2) JSON object:
     {"text":"hello","speaker":1,"max_duration_ms":10000}

Env:
  - CHUTES_TTS_SPEAK_URL: default https://chutes-csm-1b.chutes.ai/speak
  - CHUTES_TTS_API_TOKEN: bearer token (falls back to CHUTES_API_KEY)
  - CHUTES_TTS_TIMEOUT_S: HTTP timeout (default 45)
  - CHUTES_TTS_OUT_DIR: output directory (default ~/.openclaw/workspace/media/tts)
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Tuple

import requests


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _parse_input(argv: list[str]) -> Dict[str, Any]:
    raw = " ".join(argv[1:]).strip() if len(argv) > 1 else ""
    if not raw:
        raise ValueError("missing input text")

    if raw.startswith("{") and raw.endswith("}"):
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError("json input must be an object")
        return obj

    return {"text": raw}


def _extract_audio_bytes(resp: requests.Response) -> Tuple[bytes, str]:
    ctype = (resp.headers.get("content-type") or "").lower()
    if ctype.startswith("audio/"):
        ext = ".wav" if "wav" in ctype else ".mp3"
        return resp.content, ext

    # Some deployments return JSON with base64 audio payload.
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("unexpected non-audio response payload")

    # Common candidate fields.
    candidates = [
        data.get("audio_base64"),
        data.get("audio"),
        data.get("data"),
        (data.get("result") or {}).get("audio_base64") if isinstance(data.get("result"), dict) else None,
        (data.get("result") or {}).get("audio") if isinstance(data.get("result"), dict) else None,
    ]
    audio_b64 = next((v for v in candidates if isinstance(v, str) and len(v) > 32), None)
    if not audio_b64:
        raise RuntimeError(f"unexpected response keys: {sorted(list(data.keys()))}")

    # Handle data URI prefix if present.
    m = re.match(r"^data:audio/[^;]+;base64,(.*)$", audio_b64, flags=re.IGNORECASE)
    if m:
        audio_b64 = m.group(1)

    try:
        audio_bytes = base64.b64decode(audio_b64, validate=False)
    except Exception as exc:
        raise RuntimeError(f"failed to decode base64 audio: {exc}") from exc

    ext = ".wav"
    fmt = str(data.get("format") or data.get("audio_format") or "").lower()
    if "mp3" in fmt:
        ext = ".mp3"
    return audio_bytes, ext


def main() -> None:
    try:
        payload = _parse_input(sys.argv)
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")

        speaker = int(payload.get("speaker", 1))
        max_duration_ms = int(payload.get("max_duration_ms", 10000))

        url = os.getenv("CHUTES_TTS_SPEAK_URL", "https://chutes-csm-1b.chutes.ai/speak").strip()
        token = (os.getenv("CHUTES_TTS_API_TOKEN") or os.getenv("CHUTES_API_KEY") or "").strip()
        if not token:
            raise RuntimeError("missing CHUTES_TTS_API_TOKEN (or CHUTES_API_KEY)")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "*/*",
        }
        req = {"text": text, "speaker": speaker, "max_duration_ms": max_duration_ms}
        timeout_s = _env_int("CHUTES_TTS_TIMEOUT_S", 45)
        resp = requests.post(url, headers=headers, json=req, timeout=timeout_s)
        resp.raise_for_status()

        audio_bytes, ext = _extract_audio_bytes(resp)

        out_dir = Path(os.getenv("CHUTES_TTS_OUT_DIR", str(Path.home() / ".openclaw" / "workspace" / "media" / "tts")))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"csm1b-{uuid.uuid4().hex[:12]}{ext}"
        out_path.write_bytes(audio_bytes)

        # Emit OpenClaw media directives so Telegram can send a voice bubble.
        print("[[audio_as_voice]]")
        print(f"MEDIA:{out_path}")
        print(json.dumps({"ok": True, "path": str(out_path), "bytes": len(audio_bytes)}))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()

