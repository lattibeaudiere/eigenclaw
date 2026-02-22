"""
TEE wallet utility — derives the agent's Ethereum address from the KMS mnemonic.

The MNEMONIC env var is injected by EigenCompute KMS at runtime and is
cryptographically bound to this specific TEE enclave. It is stable across
restarts and redeployments, giving the agent a persistent on-chain identity.

SECURITY RULES (enforced here):
  - The mnemonic is NEVER logged, returned in API responses, or written to disk.
  - Only the derived address is exposed externally.
  - All signing happens in-memory, inside the TEE.

Usage:
    from agent.wallet import get_address, sign_message, get_account

    address = get_address()        # "0x9431Cf5DA0CE60664661341db650763B08286B18"
    account = get_account()        # eth_account.Account object for signing
"""

import os
from functools import lru_cache

# eth_account is part of web3 — included via chutes/substrate-interface deps
try:
    from eth_account import Account
    from eth_account.hdaccount import generate_mnemonic
    Account.enable_unaudited_hdwallet_features()
    _ETH_ACCOUNT_AVAILABLE = True
except ImportError:
    _ETH_ACCOUNT_AVAILABLE = False


def _get_mnemonic() -> str:
    """
    Read the KMS-injected mnemonic from the environment.
    Raises RuntimeError if not set (i.e., running outside the TEE).
    """
    mnemonic = os.environ.get("MNEMONIC", "").strip()
    if not mnemonic:
        raise RuntimeError(
            "MNEMONIC not set. This is injected by EigenCompute KMS at runtime. "
            "Outside the TEE, set a test mnemonic in .env for local development only."
        )
    return mnemonic


@lru_cache(maxsize=1)
def get_account():
    """
    Derive the agent's Ethereum Account from the KMS mnemonic.
    Uses BIP-44 derivation path m/44'/60'/0'/0/0 (standard Ethereum).
    Result is cached — the mnemonic is read once and the Account object is reused.
    """
    if not _ETH_ACCOUNT_AVAILABLE:
        raise RuntimeError(
            "eth_account not installed. Run: pip install eth-account"
        )
    mnemonic = _get_mnemonic()
    account = Account.from_mnemonic(mnemonic, account_path="m/44'/60'/0'/0/0")
    return account


def get_address() -> str:
    """
    Return the agent's Ethereum address derived from the KMS mnemonic.
    Safe to log and expose in API responses — this is just the public address.
    """
    return get_account().address


def sign_message(message: str) -> dict:
    """
    Sign an arbitrary message with the agent's TEE wallet.
    Returns the signature components — safe to return from API endpoints.
    The private key never leaves the TEE.
    """
    from eth_account.messages import encode_defunct
    account = get_account()
    msg = encode_defunct(text=message)
    signed = account.sign_message(msg)
    return {
        "address":   account.address,
        "message":   message,
        "signature": signed.signature.hex(),
        "v": signed.v,
        "r": hex(signed.r),
        "s": hex(signed.s),
    }


def wallet_info() -> dict:
    """
    Return safe public wallet info for /info endpoint.
    NEVER includes the mnemonic or private key.
    """
    try:
        address = get_address()
        return {
            "address":    address,
            "key_source": "EigenCompute KMS (TEE-bound)",
            "derivation": "m/44'/60'/0'/0/0",
        }
    except RuntimeError as e:
        return {"address": None, "error": str(e)}
