"""
HTTP server entrypoint for EigenCompute TEE deployment.
Wraps the tx labeler as a persistent REST API binding to 0.0.0.0.

Endpoints:
  POST /label        — label a single tx (JSON body: {"description": "..."})
  POST /label/batch  — label multiple txs (JSON body: [{"description": "..."}, ...])
  GET  /health       — liveness probe (returns {"status": "ok"})
  GET  /info         — returns model/endpoint config (public vars only)

Environment variables (injected by TEE at runtime):
  EIGENCLOUD_API_KEY  — required
  EIGENAI_BASE_URL    — defaults to mainnet
  EIGENAI_MODEL       — defaults to gpt-oss-120b-f16
  APP_PORT            — defaults to 8080
  NETWORK_PUBLIC      — shown in /info (use _PUBLIC suffix for transparency)
"""

import os
import json
import http.server
from urllib.parse import urlparse
from dotenv import load_dotenv
from chutes.client import classify, active_backend
from agent.wallet import wallet_info

load_dotenv()

PORT    = int(os.getenv("APP_PORT", "8080"))
NETWORK = os.getenv("NETWORK_PUBLIC", "mainnet")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[{self.address_string()}] {format % args}")

    def send_json(self, code: int, data):
        body = json.dumps(data, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return None
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json(200, {"status": "ok"})
        elif path == "/info":
            self.send_json(200, {
                "backend": active_backend(),
                "network": NETWORK,
                "wallet":  wallet_info(),   # address only — mnemonic never exposed
            })
        else:
            self.send_json(404, {"error": "not_found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self.read_json_body()
        except Exception:
            self.send_json(400, {"error": "invalid_json_body"})
            return

        if path == "/label":
            if not isinstance(body, dict) or "description" not in body:
                self.send_json(400, {"error": "body must be {\"description\": \"...\"}"})
                return
            result = classify(body["description"])
            self.send_json(200, result)

        elif path == "/label/batch":
            if not isinstance(body, list):
                self.send_json(400, {"error": "body must be a JSON array"})
                return
            results = []
            for tx in body:
                desc = tx.get("description", "")
                if desc:
                    label = classify(desc)
                else:
                    label = {"error": "no_description"}
                results.append({**tx, "label": label})
            self.send_json(200, results)

        else:
            self.send_json(404, {"error": "not_found"})


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"EigenClaw TEE server listening on 0.0.0.0:{PORT}")
    print(f"  Backend : {active_backend()}")
    print(f"  Network : {NETWORK}")
    server.serve_forever()
