"""
QuantAgri — Ollama Cloud Client
Thin wrapper around the Ollama Cloud REST API.
Endpoint: https://ollama.com/api/chat
Auth:     Authorization: Bearer $OLLAMA_API_KEY
"""

import json
import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

ENDPOINT = "https://ollama.com/api/chat"
MAX_RETRIES = 3
RETRY_DELAY = 8   # seconds


def _get_key() -> str:
    key = os.getenv("OLLAMA_API_KEY", "")
    if not key:
        raise RuntimeError(
            "OLLAMA_API_KEY not set. "
            "Add it to .env locally or as a GitHub Actions secret."
        )
    return key


def chat(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.2,
    as_json: bool = True,
    system: str | None = None,
) -> str:
    """
    Send a chat request to Ollama Cloud. Returns the response content string.

    Args:
        prompt:      User message content.
        model:       Ollama model tag. Defaults to OLLAMA_MODEL env var or qwen2.5:7b.
        temperature: Sampling temperature (lower = more deterministic).
        as_json:     If True, sets format='json' to force structured output.
        system:      Optional system message.
    """
    model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    key   = _get_key()

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model":    model,
        "messages": messages,
        "stream":   False,
        "options":  {"temperature": temperature},
    }
    if as_json:
        payload["format"] = "json"

    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {key}",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                ENDPOINT,
                headers=headers,
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]
        except requests.HTTPError as e:
            print(f"  [HTTP {resp.status_code}] attempt {attempt}/{MAX_RETRIES}: {e}")
            if resp.status_code in (401, 403):
                raise RuntimeError("Invalid or expired OLLAMA_API_KEY") from e
        except requests.RequestException as e:
            print(f"  [NET ERR] attempt {attempt}/{MAX_RETRIES}: {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)

    raise RuntimeError(f"Ollama Cloud request failed after {MAX_RETRIES} attempts")


def chat_json(prompt: str, model: str | None = None, system: str | None = None) -> dict:
    """
    Like chat() but parses and returns a dict.
    Strips any accidental markdown fences before parsing.
    """
    raw = chat(prompt, model=model, as_json=True, system=system)
    # Strip ```json ... ``` fences if the model wraps despite format=json
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[1:])
        cleaned = cleaned.rstrip("`").strip()
    # Extract outermost JSON object
    start = cleaned.find("{")
    end   = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in response:\n{raw[:300]}")
    return json.loads(cleaned[start:end])
