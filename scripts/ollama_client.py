"""
QuantAgri — Ollama Cloud Client
Endpoint: https://ollama.com/api/chat

Confirmed available models (from https://ollama.com/api/tags):
  gpt-oss:20b        <- default, fast
  gpt-oss:120b       <- higher quality
  gemma3:4b          <- very fast, small
  gemma3:12b
  gemma4:31b
  deepseek-v3.1:671b <- highest quality
  qwen3-coder:480b

NOTE: Do NOT use -cloud suffix via the remote API.
"""

import json, os, time
from typing import Any
import requests
from dotenv import load_dotenv

load_dotenv()

ENDPOINT    = "https://ollama.com/api/chat"
MAX_RETRIES = 3
RETRY_DELAY = 8


def _get_key() -> str:
    key = os.getenv("OLLAMA_API_KEY", "")
    if not key:
        raise RuntimeError("OLLAMA_API_KEY not set.")
    return key


def chat(prompt, model=None, temperature=0.2, as_json=True, system=None):
    model = model or os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
    key   = _get_key()

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model, "messages": messages,
        "stream": False, "options": {"temperature": temperature},
    }
    if as_json:
        payload["format"] = "json"

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(ENDPOINT, headers=headers, json=payload, timeout=120)

            if resp.status_code == 404:
                raise RuntimeError(
                    f"Model '{model}' not found on Ollama Cloud API.\n"
                    f"Available: gpt-oss:20b, gpt-oss:120b, gemma3:4b, gemma3:12b, "
                    f"gemma4:31b, deepseek-v3.1:671b\n"
                    f"Check: https://ollama.com/api/tags\n"
                    f"Do NOT use -cloud suffix via the remote API."
                )
            if resp.status_code in (401, 403):
                raise RuntimeError("Invalid or expired OLLAMA_API_KEY")

            resp.raise_for_status()
            return resp.json()["message"]["content"]

        except RuntimeError:
            raise
        except requests.HTTPError as e:
            print(f"  [HTTP {resp.status_code}] attempt {attempt}/{MAX_RETRIES}: {e}")
        except requests.RequestException as e:
            print(f"  [NET ERR] attempt {attempt}/{MAX_RETRIES}: {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)

    raise RuntimeError(f"Ollama Cloud failed after {MAX_RETRIES} attempts")


def chat_json(prompt, model=None, system=None):
    raw     = chat(prompt, model=model, as_json=True, system=system)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[1:]).rstrip("`").strip()
    start = cleaned.find("{")
    end   = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON in response:\n{raw[:300]}")
    return json.loads(cleaned[start:end])
