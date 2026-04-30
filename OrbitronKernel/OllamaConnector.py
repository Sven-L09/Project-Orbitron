import json
import os
from typing import Any

import requests


class OllamaConnector:
    API_BASE_URL_DEFAULT = "https://ollama.com/api"
    API_KEY_DEFAULT = ""  # Prefer env var/config; keep empty by default.
    MODEL_DEFAULT = "kimi-k2.5:cloud"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str = MODEL_DEFAULT,
    ):
        self.base_url = (base_url or self.API_BASE_URL_DEFAULT).rstrip("/")
        self.api_key = api_key or os.getenv("OLLAMA_API_KEY") or self.API_KEY_DEFAULT
        self.model = model

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        think: bool | str | None = None,
        timeout_s: int = 180,
    ) -> dict[str, Any]:
        """Call Ollama /api/chat.

        Returns the parsed response as a dict. If the server streams NDJSON,
        the returned `message` is aggregated across chunks (content/thinking/tool_calls).
        """
        url = self._endpoint_url("chat")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        if tools is not None:
            payload["tools"] = tools
        if think is not None:
            payload["think"] = think

        # Cloud endpoints may return NDJSON even when stream=false.
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            stream=True,
            timeout=(10, timeout_s),
        )
        response.raise_for_status()
        return self._parse_ndjson_or_json_response(response)

    def generate_response(self, prompt: str, *, timeout_s: int = 180) -> str:
        """Backward-compatible helper: one-turn chat returning assistant content."""
        resp = self.chat(
            [{"role": "user", "content": prompt}],
            stream=False,
            think=None,
            timeout_s=timeout_s,
        )
        message = resp.get("message") or {}
        return str(message.get("content") or "")

    def _endpoint_url(self, endpoint: str) -> str:
        base = self.base_url.rstrip("/")
        # Allow base_url to be either ".../api" or "...".
        if base.endswith("/api"):
            return f"{base}/{endpoint.lstrip('/')}"
        return f"{base}/api/{endpoint.lstrip('/')}"

    def _parse_ndjson_or_json_response(self, response: requests.Response) -> dict[str, Any]:
        aggregated_message: dict[str, Any] = {"role": "assistant", "content": ""}
        tool_calls: list[dict[str, Any]] = []
        raw_last_obj: dict[str, Any] | None = None
        saw_json = False

        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
                saw_json = True
            except json.JSONDecodeError:
                continue

            raw_last_obj = obj

            if obj.get("error"):
                raise RuntimeError(str(obj["error"]))

            msg = obj.get("message") or {}
            if isinstance(msg, dict):
                if msg.get("role"):
                    aggregated_message["role"] = msg["role"]

                thinking = msg.get("thinking")
                if thinking:
                    aggregated_message["thinking"] = str(aggregated_message.get("thinking") or "") + str(thinking)

                content = msg.get("content")
                if content:
                    aggregated_message["content"] = str(aggregated_message.get("content") or "") + str(content)

                if msg.get("tool_calls"):
                    if isinstance(msg["tool_calls"], list):
                        tool_calls.extend(msg["tool_calls"])

                if msg.get("images") is not None:
                    aggregated_message["images"] = msg.get("images")

            if obj.get("done") is True:
                break

        if not saw_json:
            # Fallback: try parse as a single JSON object.
            try:
                raw_last_obj = response.json()
            except Exception:
                return {"message": aggregated_message, "done": True}

        result: dict[str, Any] = dict(raw_last_obj or {})

        if tool_calls:
            # De-duplicate tool calls (best-effort).
            seen = set()
            unique_calls: list[dict[str, Any]] = []
            for call in tool_calls:
                try:
                    key = json.dumps(call, sort_keys=True, ensure_ascii=False)
                except Exception:
                    key = str(call)
                if key in seen:
                    continue
                seen.add(key)
                unique_calls.append(call)
            aggregated_message["tool_calls"] = unique_calls

        result["message"] = aggregated_message
        return result