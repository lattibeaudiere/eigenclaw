# DeFEyes Ghost-Buster Pulse (4h Interval)

- **API Auth Contract (mandatory)**:
  - For DeFEyes paid routes, always use `X-API-Key`, never `Authorization: Bearer`.
  - Canonical pattern:
    - `curl -H "X-API-Key: $DEFEYES_API_KEY" "https://defeyes-api.vercel.app/api/events?network=arbitrum&limit=50"`
  - A `402 Payment Required` on `/api/events` usually means the request did not include a valid `X-API-Key`; retry with the exact header before concluding paywall blockage.
  - With a valid Pro key, no x402 payment flow is required for this heartbeat audit.

- **Audit Aave Logic**: Scan the last 50 transactions for the `action_type: BORROW` or `WITHDRAW`.
- **Verify Value Capture**: If a transaction has a NULL amount but touches the Merkle Escrow (`0xF611AeB...`), re-calculate using the $10^{27}$ (Ray) scaling logic.
- **Flag Drift**: If any "Ghost Assets" are found, draft a summary for the API dev with the TX hash and the missing value.
- **Security Check**: Verify no `.env` files have been re-added to the git staging area.

