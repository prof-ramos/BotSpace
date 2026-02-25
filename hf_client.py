import os
from typing import Any, Dict, List

import requests

HF_TOKEN = os.getenv("HF_TOKEN")
HF_TEXT_MODEL = os.getenv("HF_TEXT_MODEL", "microsoft/Phi-3.5-mini-instruct")
HF_INFERENCE_URL = os.getenv(
    "HF_INFERENCE_URL",
    f"https://api-inference.huggingface.co/models/{HF_TEXT_MODEL}",
)

if not HF_TOKEN:
    raise RuntimeError("HF_TOKEN nao definido.")

_SESSION = requests.Session()


def _messages_to_prompt(messages: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    for m in messages:
        role = m.get("role", "user").upper()
        content = m.get("content", "")
        lines.append(f"[{role}]\n{content}")
    lines.append("[ASSISTANT]\n")
    return "\n\n".join(lines)


def call_hf(messages: List[Dict[str, str]], max_tokens: int = 500, temperature: float = 0.2) -> str:
    prompt = _messages_to_prompt(messages)

    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_tokens,
            "temperature": temperature,
            "return_full_text": False,
        },
    }

    response = _SESSION.post(HF_INFERENCE_URL, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    data = response.json()

    # Typical formats from HF Inference API
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if "generated_text" in data[0]:
            return str(data[0]["generated_text"]).strip()

    if isinstance(data, dict):
        if "generated_text" in data:
            return str(data["generated_text"]).strip()
        if "error" in data:
            raise RuntimeError(f"HF inference error: {data['error']}")

    raise RuntimeError(f"HF inference response format unexpected: {data}")
