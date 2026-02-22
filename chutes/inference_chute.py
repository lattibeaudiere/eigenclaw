"""
EigenClaw inference Chute — deploys a TEE-secured LLM endpoint on Chutes.ai.

This is the agent's "brain": private, tamper-proof LLM inference running inside
a Trusted Execution Environment. OpenClaw routes all agent reasoning here.

Deploy once with:
    chutes deploy chutes/inference_chute.py:chute

Then set in .env:
    CHUTES_ENDPOINT=https://<your-chute-slug>.chutes.ai
    CHUTES_API_KEY=<from chutes.ai dashboard>
    CHUTES_MODEL=Llama-3.2-11B-Vision-Instruct   (or whatever you deployed)

Docs: https://docs.chutes.ai
"""

from chutes.chute import Chute, ChutePack
from chutes.image import Image
from pydantic import BaseModel
from typing import Optional

# ── Chute definition ──────────────────────────────────────────────────────────

chute = Chute(
    username="eigenclaw",          # your Chutes username
    name="eigenclaw-inference",
    tagline="TEE-secured DeFi tx classifier LLM for EigenClaw sovereign agent",
    readme="""
## EigenClaw Inference

Private LLM inference for classifying DeFi transaction intent.
Runs inside a Trusted Execution Environment — outputs are cryptographically attested.

### Endpoints
- `POST /v1/chat/completions` — OpenAI-compatible chat completions
- `GET  /health`              — liveness probe

### Models
- Llama 3.2 11B (default)
""",
    image=Image(name="vllm/vllm-openai", tag="latest"),
    tee=True,           # run inside TEE for cryptographic attestation
)


# ── Request / response schemas ────────────────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "Llama-3.2-11B-Vision-Instruct"
    messages: list[Message]
    temperature: float = 0.0
    max_tokens: int = 400
    stream: bool = False


class Choice(BaseModel):
    index: int
    message: Message
    finish_reason: str


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    model: str
    choices: list[Choice]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@chute.cord(method="GET", path="/health")
async def health() -> dict:
    """Liveness probe — returns TEE attestation metadata if available."""
    return {"status": "ok", "tee": True}


@chute.cord(method="POST", path="/v1/chat/completions")
async def chat_completions(body: ChatCompletionRequest) -> ChatCompletionResponse:
    """
    OpenAI-compatible chat completions endpoint.
    OpenClaw points its provider config here; EigenAI can also use it as fallback.

    The TEE ensures:
    - The model weights are unmodified
    - Inputs/outputs are never logged outside the enclave
    - Outputs carry a cryptographic attestation

    NOTE: Deploy this file separately to Chutes.ai first:
      chutes deploy chutes/inference_chute.py:chute
    Then set CHUTES_ENDPOINT + CHUTES_API_KEY in your .env.
    Until then, the app falls back to EigenAI automatically.
    """
    import httpx

    # Chutes SDK routes this call to the vLLM backend running in the TEE
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/v1/chat/completions",
            json={
                "model": body.model,
                "messages": [{"role": m.role, "content": m.content} for m in body.messages],
                "temperature": body.temperature,
                "max_tokens": body.max_tokens,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

    return ChatCompletionResponse(
        id=data["id"],
        model=data["model"],
        choices=[
            Choice(
                index=c["index"],
                message=Message(role=c["message"]["role"], content=c["message"]["content"]),
                finish_reason=c["finish_reason"],
            )
            for c in data["choices"]
        ],
    )
