# DeFEyes Ghost-Buster Pulse (4h Interval)

- **Audit Aave Logic**: Scan the last 50 transactions for the `action_type: BORROW` or `WITHDRAW`.
- **Verify Value Capture**: If a transaction has a NULL amount but touches the Merkle Escrow (`0xF611AeB...`), re-calculate using the $10^{27}$ (Ray) scaling logic.
- **Flag Drift**: If any "Ghost Assets" are found, draft a summary for the API dev with the TX hash and the missing value.
- **Security Check**: Verify no `.env` files have been re-added to the git staging area.

