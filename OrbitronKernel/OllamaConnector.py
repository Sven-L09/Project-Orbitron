import concurrent.futures
import json
import os
import queue
import time
from typing import Any

import requests


class OllamaConnector:
    API_BASE_URL_DEFAULT = "https://ollama.com/api"
    API_KEY_DEFAULT = ""  # Prefer env var/config; keep empty by default.
    MODEL_DEFAULT = "nemotron-3-super:cloud"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str = MODEL_DEFAULT,
    ):
        self.base_url = (base_url or self.API_BASE_URL_DEFAULT).rstrip("/")
        self.api_key = api_key or os.getenv("OLLAMA_API_KEY") or self.API_KEY_DEFAULT
        self.model = model

    def _do_post(
        self,
        session: requests.Session,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        stream: bool,
        timeout: tuple[int, int],
        result_queue: queue.Queue,
        error_queue: queue.Queue,
    ) -> None:
        """Run the HTTP POST in a background thread."""
        try:
            response = session.post(
                url,
                headers=headers,
                json=payload,
                stream=stream,
                timeout=timeout,
            )
            result_queue.put(response)
        except Exception as e:
            error_queue.put(e)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        think: bool | str | None = None,
        timeout_s: int = 3600,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Call Ollama /api/chat with automatic retry on transient failures.

        Uses a background thread with an absolute deadline to prevent
        TCP-level hangs where requests' internal timeout does not trigger
        (e.g. zombie connections on Windows).

        Retries on: Timeout, ConnectionError, HTTP 5xx.
        Does NOT retry on: HTTP 4xx (client errors), invalid JSON.

        Returns the parsed response as a dict.
        """
        import logging
        logger = logging.getLogger("OllamaConnector")

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

        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            start_time = time.time()
            session = requests.Session()
            result_queue: queue.Queue = queue.Queue()
            error_queue: queue.Queue = queue.Queue()
            thread: threading.Thread | None = None
            try:
                logger.info(
                    "[Ollama] Sending chat request to %s (model=%s, timeout=%ds, messages=%d, attempt=%d/%d)",
                    url, self.model, timeout_s, len(messages), attempt, max_retries,
                )

                import threading
                thread = threading.Thread(
                    target=self._do_post,
                    args=(session, url, headers, payload, stream, (10, timeout_s), result_queue, error_queue),
                    daemon=True,
                )
                thread.start()
                thread.join(timeout=timeout_s)

                if thread.is_alive():
                    # Absolute deadline exceeded — the server (or a proxy) left the
                    # connection open without sending data. Force-close the session.
                    logger.warning(
                        "[Ollama] Absolute deadline of %ds exceeded — force-closing connection (attempt %d/%d)",
                        timeout_s, attempt, max_retries,
                    )
                    session.close()
                    raise requests.exceptions.Timeout(
                        f"Ollama request exceeded absolute deadline of {timeout_s}s"
                    )

                # Thread finished — check for errors first
                if not error_queue.empty():
                    raise error_queue.get()

                # Thread finished successfully
                response = result_queue.get()
                response.raise_for_status()

                if stream:
                    result = self._parse_ndjson_or_json_response(response, deadline=start_time + timeout_s)
                else:
                    result = response.json()

                elapsed = time.time() - start_time
                content = str((result.get("message") or {}).get("content") or "")
                logger.info(
                    "[Ollama] Response received (%d chars, done=%s, elapsed=%.1fs, attempt=%d)",
                    len(content), result.get("done", False), elapsed, attempt,
                )
                return result

            except requests.exceptions.Timeout as e:
                last_error = e
                logger.warning(
                    "[Ollama] Request timed out after %ds (attempt %d/%d)",
                    timeout_s, attempt, max_retries,
                )
            except requests.exceptions.ConnectionError as e:
                last_error = e
                logger.warning(
                    "[Ollama] Connection error: %s (attempt %d/%d)",
                    e, attempt, max_retries,
                )
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else 0
                # 5xx = server error, retryable. 4xx = client error, don't retry.
                if status >= 500:
                    last_error = e
                    logger.warning(
                        "[Ollama] HTTP %d server error (attempt %d/%d)",
                        status, attempt, max_retries,
                    )
                else:
                    logger.error("[Ollama] HTTP %d client error — not retrying", status)
                    raise RuntimeError(f"Ollama HTTP {status} error: {e}") from e
            except Exception as e:
                logger.error("[Ollama] Request failed: %s — not retrying", e)
                raise RuntimeError(f"Ollama request failed: {e}") from e
            finally:
                session.close()

            # Exponential backoff before retry: 2s, 4s, 8s...
            if attempt < max_retries:
                backoff = 2 ** attempt
                logger.info("[Ollama] Retrying in %d seconds...", backoff)
                time.sleep(backoff)

        # All retries exhausted
        logger.error("[Ollama] All %d attempts failed. Last error: %s", max_retries, last_error)
        raise RuntimeError(
            f"Ollama request failed after {max_retries} attempts. Last error: {last_error}"
        ) from last_error

    def generate_response(self, prompt: str, *, timeout_s: int = 3600) -> str:
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

    def _parse_ndjson_or_json_response(
        self,
        response: requests.Response,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        aggregated_message: dict[str, Any] = {"role": "assistant", "content": ""}
        tool_calls: list[dict[str, Any]] = []
        raw_last_obj: dict[str, Any] | None = None
        saw_json = False

        for raw_line in response.iter_lines(decode_unicode=True):
            if deadline is not None and time.time() > deadline:
                logger = logging.getLogger("OllamaConnector")
                logger.warning("[Ollama] Stream parsing aborted: deadline exceeded")
                break

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