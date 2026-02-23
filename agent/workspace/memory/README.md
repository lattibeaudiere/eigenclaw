# memory/

This folder holds DeFive’s continuous memory logs.

- The automation pulse appends a daily log file here (e.g., `2026-02-23.md`).
- On container startup, `entrypoint.sh` generates `memory/_ROLLUP.md` by concatenating all `*.md` files in this folder (excluding `_ROLLUP.md`).

