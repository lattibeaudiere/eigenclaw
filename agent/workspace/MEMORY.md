# Memory

Persistent context across sessions. Update this file when learning important facts.

## Deployment

- App ID: `0x0c976F51abC812e7f2b1767652085b0588556a94`
- Domain: `eigenclaw.xyz`
- Network: Sepolia (testnet)
- Gateway port: 18789

## Available APIs

- **Chutes**: LLM inference (GLM-4.7-TEE primary, DeepSeek/Qwen fallbacks)
- **DeFEyes**: Transaction enrichment and labeling (`DEFEYES_API_KEY`)
- **Arbitrum JSON-RPC**: On-chain ground truth (`ARBITRUM_RPC_URL` or default `https://arb1.arbitrum.io/rpc`)

## Arbitrum RPC (Ground Truth)

- **Core calls**:
  - `eth_getTransactionByHash` (who/where/value/calldata)
  - `eth_getTransactionReceipt` (status + emitted `logs[]`)
  - `eth_getLogs` (historical event scans by address/topics + block range)

## Protocol Registry (Arbitrum)

| Protocol         | Address                                      |
|------------------|----------------------------------------------|
| Aave V3 Pool     | `0x794a61358D6845594F94dc1DB02A252b5b4814aD` |
| KyberSwap Router | `0x6131B5fae19EA4f9D964eAc0408E4408b66337b5` |
| USDT             | `0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9` |
| WETH             | `0x82aF49447D8a07e3bd95BD0d56f35241523fBab1` |

## Audit Log

### 2026-02-23 — Ontology Drift Incident (Tx: 0xc1162a...)

**What happened:** First live Truth-Seeker test. Agent correctly identified the routing path (User → ETH → KyberSwap → USDT → Aave) but incorrectly flagged the DeFEyes label `SUPPLY USDT` as a distortion.

**Root cause:** Agent focused on the journey (intermediate swaps) instead of the outcome (Aave Pool `Supply` event). It also:
- Misattributed KyberSwap router as 1inch V6
- Used 4-byte selectors instead of 32-byte topic0 hashes
- Mislabeled WETH (0x82aF...) as WBTC
- Tried to invent `SWAP_AND_SUPPLY` label outside the schema

**Fix applied:** "Hierarchy of Truth" protocol encoded in AGENTS.md — protocol pool event logs are Primary Truth; intermediate routing is informational only. MVE bundle format enforced. Hardcoded registry added.

**Lesson:** Always anchor on the protocol outcome event. The DeFEyes `eventListener.js` correctly treats the Aave Pool log as ground truth. The agent must do the same.

## Session Log

- First boot: 2026-02-23
- Ontology Drift calibration: 2026-02-23
