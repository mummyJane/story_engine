# story_engine/llm/lmstudio_client.py  (or wherever your client lives)

import os
import requests
from typing import Optional


class LMStudioClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        default_max_tokens: Optional[int] = None,
        default_temperature: float = 0.7,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.default_max_tokens = default_max_tokens
        self.default_temperature = default_temperature

        # This will be filled from /v1/models or env if possible
        self.model_max_tokens: Optional[int] = None
        self._detect_model_limits()

    # ---------------------------------------------------------
    # Model metadata / max token detection
    # ---------------------------------------------------------
    def _detect_model_limits(self) -> None:
        """
        Try to detect the model's max context length so we can pick
        sensible max_tokens automatically.

        Priority:
          1) Env var STORY_ENGINE_LM_MAX_TOKENS
          2) /v1/models metadata (if LM Studio exposes it)
          3) Fall back to default_max_tokens (if provided)
        """
        # 1) Env override
        env_val = os.getenv("STORY_ENGINE_LM_MAX_TOKENS")
        if env_val:
            try:
                self.model_max_tokens = int(env_val)
                print(f"[LMStudioClient] Using STORY_ENGINE_LM_MAX_TOKENS={self.model_max_tokens}")
                return
            except ValueError:
                print(f"[LMStudioClient] Invalid STORY_ENGINE_LM_MAX_TOKENS={env_val!r}, ignoring")

        # 2) Try /v1/models
        try:
            resp = requests.get(f"{self.base_url}/v1/models", timeout=3)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            print(f"[LMStudioClient] Could not query /v1/models: {e}")
            return

        for m in payload.get("data", []):
            mid = m.get("id") or m.get("name")
            if mid != self.model:
                continue

            # Try a few common keys used for context length
            for key in ("context_length", "max_context_length", "max_total_tokens"):
                if key in m:
                    try:
                        self.model_max_tokens = int(m[key])
                        print(f"[LMStudioClient] Model {self.model} context={self.model_max_tokens} via '{key}'")
                        return
                    except (TypeError, ValueError):
                        pass

            # Some servers put it in metadata
            md = m.get("metadata") or {}
            for key in ("context_length", "max_context_length"):
                if key in md:
                    try:
                        self.model_max_tokens = int(md[key])
                        print(f"[LMStudioClient] Model {self.model} context={self.model_max_tokens} via metadata['{key}']")
                        return
                    except (TypeError, ValueError):
                        pass

        # 3) No info found; we'll fall back to default_max_tokens
        if self.default_max_tokens:
            print(f"[LMStudioClient] No context info from server; will use default_max_tokens={self.default_max_tokens}")

    def _pick_max_tokens(self, requested: Optional[int]) -> Optional[int]:
        """
        Decide what max_tokens to send to the API, based on:
          - requested: per-call override
          - model_max_tokens: from /v1/models or env
          - default_max_tokens: constructor default
        Leaves headroom for the prompt if model_max_tokens is known.
        """
        # If caller passed something explicitly, cap it at model limit
        if requested is not None:
            if self.model_max_tokens is None:
                return requested
            # leave some space for the prompt
            return max(16, min(requested, self.model_max_tokens - 256))

        # No explicit request; pick something ourselves
        if self.model_max_tokens is not None:
            # Simple strategy: half the context for output
            return max(16, self.model_max_tokens // 2)

        # Fall back to default_max_tokens, or None (server decides)
        return self.default_max_tokens

    # ---------------------------------------------------------
    # Completion call
    # ---------------------------------------------------------
    def complete(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Simple text completion wrapper for LM Studio's OpenAI-compatible API.
        """
        max_tokens = self._pick_max_tokens(max_tokens)
        temp = self.default_temperature if temperature is None else temperature

        body = {
            "model": self.model,
            "prompt": prompt,
            "temperature": temp,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        r = requests.post(f"{self.base_url}/v1/completions", json=body, timeout=120)
        r.raise_for_status()
        data = r.json()
        print(f"data - {data}")
        # Adjust this if you're using chat/completions instead
        return data["choices"][0]["text"]
