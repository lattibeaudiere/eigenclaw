#!/usr/bin/env python3
"""
Lightweight local Whisper-compatible CLI wrapper for OpenClaw STT.

Supports a subset of the common `whisper` CLI invocation pattern:
  whisper <audio_path> [--model base] [--language en]
Unknown flags are ignored so OpenClaw can pass extra args safely.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from faster_whisper import WhisperModel


def _arg_value(flag: str, args: list[str]) -> str | None:
    for i, token in enumerate(args):
        if token == flag and i + 1 < len(args):
            return args[i + 1]
    return None


def _audio_path(args: list[str]) -> str | None:
    for token in args:
        if token.startswith("-"):
            continue
        return token
    return None


def main() -> int:
    args = sys.argv[1:]
    audio = _audio_path(args)
    if not audio:
        print("missing audio path", file=sys.stderr)
        return 2

    audio_path = Path(audio)
    if not audio_path.exists():
        print(f"audio file not found: {audio_path}", file=sys.stderr)
        return 2

    model_size = _arg_value("--model", args) or os.getenv("WHISPER_MODEL_SIZE", "base")
    language = _arg_value("--language", args) or None
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    model_dir = os.getenv("WHISPER_MODEL_DIR", "/tmp/whisper-models")

    model = WhisperModel(model_size, device="cpu", compute_type=compute_type, download_root=model_dir)
    segments, _info = model.transcribe(str(audio_path), language=language, vad_filter=True)
    text = " ".join(seg.text.strip() for seg in segments if seg.text).strip()
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

