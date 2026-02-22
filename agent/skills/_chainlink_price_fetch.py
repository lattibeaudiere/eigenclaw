"""
Fetches latest price from a Chainlink Aggregator via JSON-RPC.
Called by the chainlink_price skill — runs inside the EigenCompute TEE.

Usage (by skill runner):
    python3 _chainlink_price_fetch.py ETH/USD arbitrum
    python3 _chainlink_price_fetch.py BTC/USD mainnet
    python3 _chainlink_price_fetch.py USDC/USD sepolia
"""

import sys
import json
import datetime
import urllib.request
import urllib.error

# ── Chainlink feed addresses (latestRoundData AggregatorV3Interface) ──────────
# ABI selector for latestRoundData(): 0xfeaf968c
LATEST_ROUND_DATA_SELECTOR = "0xfeaf968c"

FEEDS = {
    "arbitrum": {
        "rpc": "https://arb1.arbitrum.io/rpc",
        "ETH/USD":  "0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612",
        "BTC/USD":  "0x6ce185860a4963106506C203335A2910413708e9",
        "USDC/USD": "0x50834F3163758fcC1Df9973b6e91f0F0F0434aD3",
        "LINK/USD": "0x86E53CF1B873E8f4C2f1fF9E7f47ad4bE91Cbab",
        "ARB/USD":  "0xb2A824043730FE05F3DA2efaFa1CBbe83fa548D7",
    },
    "mainnet": {
        "rpc": "https://eth.llamarpc.com",
        "ETH/USD":  "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",
        "BTC/USD":  "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c",
        "USDC/USD": "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6",
        "LINK/USD": "0x2c1d072e956AFFC0D435Cb7AC38EF18d24d9127c",
    },
    "sepolia": {
        "rpc": "https://rpc.sepolia.org",
        "ETH/USD":  "0x694AA1769357215DE4FAC081bf1f309aDC325306",
        "BTC/USD":  "0x1b44F3514812d835EB1BDB0acB33d3fA3351Ee43",
        "USDC/USD": "0xA2F78ab2355fe2f984D808B5CeE7FD0A93D5270E",
    },
}


def eth_call(rpc_url: str, to: str, data: str) -> str:
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
        "id": 1,
    }).encode()
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["result"]


def decode_latest_round_data(hex_result: str) -> dict:
    """
    latestRoundData() returns:
      (uint80 roundId, int256 answer, uint256 startedAt,
       uint256 updatedAt, uint80 answeredInRound)
    Each value is 32 bytes, ABI-encoded.
    """
    data = hex_result[2:]   # strip 0x
    chunk = lambda i: int(data[i*64:(i+1)*64], 16)
    round_id    = chunk(0)
    answer      = chunk(1)
    updated_at  = chunk(3)
    return {
        "round_id":   round_id,
        "raw_answer": answer,
        "updated_at": updated_at,
    }


def get_decimals(rpc_url: str, feed_address: str) -> int:
    """Call decimals() → 0x313ce567"""
    result = eth_call(rpc_url, feed_address, "0x313ce567")
    return int(result, 16)


def main():
    pair    = sys.argv[1].upper() if len(sys.argv) > 1 else "ETH/USD"
    network = sys.argv[2].lower() if len(sys.argv) > 2 else "arbitrum"

    if network not in FEEDS:
        print(json.dumps({"error": f"Unknown network: {network}. Choose from {list(FEEDS.keys())}"}))
        sys.exit(1)

    network_config = FEEDS[network]
    rpc_url = network_config["rpc"]

    if pair not in network_config:
        available = [k for k in network_config if k != "rpc"]
        print(json.dumps({"error": f"Feed '{pair}' not found on {network}. Available: {available}"}))
        sys.exit(1)

    feed_address = network_config[pair]

    try:
        raw     = eth_call(rpc_url, feed_address, LATEST_ROUND_DATA_SELECTOR)
        decoded = decode_latest_round_data(raw)
        decimals = get_decimals(rpc_url, feed_address)
        price   = decoded["raw_answer"] / (10 ** decimals)
        updated = datetime.datetime.utcfromtimestamp(decoded["updated_at"]).isoformat() + "Z"

        result = {
            "pair":       pair,
            "price":      round(price, 6),
            "decimals":   decimals,
            "updated_at": updated,
            "round_id":   str(decoded["round_id"]),
            "network":    network,
            "feed":       feed_address,
        }
        print(json.dumps(result, indent=2))

    except urllib.error.URLError as e:
        print(json.dumps({"error": f"RPC request failed: {e}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
