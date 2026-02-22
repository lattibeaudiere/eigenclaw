"""
Called directly by OpenClaw's exec tool when the tx_labeler skill is triggered.
OpenClaw passes the user's tx description as argv[1] and reads stdout as the result.

This script uses Chutes (primary) or EigenAI (fallback) for classification —
whichever is configured in the environment at TEE runtime.
"""

import sys
import json
sys.path.insert(0, "/app")

from chutes.client import classify

if len(sys.argv) < 2:
    print(json.dumps({"error": "No transaction description provided"}))
    sys.exit(1)

description = " ".join(sys.argv[1:])

try:
    result = classify(description)
    print(json.dumps(result, indent=2))
except Exception as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(1)
