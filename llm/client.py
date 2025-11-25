# story_engine/llm/client.py
import requests
from typing import List, Optional


class LLMClient:
    """
    Simple wrapper around an OpenAI-compatible chat API (e.g. LM Studio server).
    """

    def __init__(self, base_url: str, model_name: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.api_key = api_key or "lm-studio"  # LM Studio usually ignores this, but it's fine to send

    def complete(
        self,
        prompt: str,
        max_tokens: int = 8192,
        temperature: float = 0.6,
    ) -> str:
        """
        Sends a single-prompt chat completion request and returns the model's reply text.
        """
        url = f"{self.base_url}/v1/chat/completions"

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        print("payload ", payload)

        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        # OpenAI-style: choices[0].message.content
        return data["choices"][0]["message"]["content"]

    def list_models(self):
        """
        Ask LM Studio which models are available.

        Tries the richer REST API /api/v0/models first, falls back to /v1/models.
        Returns a list of dicts: {id, type, arch, state, max_context_length}.
        """
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # Try LM Studio REST API v0 first (more info). :contentReference[oaicite:1]{index=1}
        try:
            resp = requests.get(f"{self.base_url}/api/v0/models", headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = []
                for m in data.get("data", []):
                    models.append(
                        {
                            "id": m.get("id"),
                            "type": m.get("type"),
                            "arch": m.get("arch"),
                            "state": m.get("state"),
                            "max_context_length": m.get("max_context_length"),
                        }
                    )
                if models:
                    return models
        except Exception:
            pass

        # Fallback to OpenAI-compatible /v1/models :contentReference[oaicite:2]{index=2}
        resp = requests.get(f"{self.base_url}/v1/models", headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = []
        for m in data.get("data", []):
            models.append(
                {
                    "id": m.get("id"),
                    "type": m.get("object", None),
                    "arch": None,
                    "state": None,
                    "max_context_length": None,
                }
            )
        return models