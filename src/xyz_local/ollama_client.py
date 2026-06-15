"""Robust Ollama client with special handling for models that don't support tools (400 errors)."""

from __future__ import annotations

import json
import re
from typing import Any, AsyncGenerator, Optional

import httpx
from rich.console import Console
from rich.panel import Panel

console = Console()


def _parse_tool_call_fallback(text: str) -> list[dict[str, Any]]:
    """Very robust parser for local models."""
    tool_calls: list[dict[str, Any]] = []
    text = text.strip()

    for match in re.finditer(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, re.DOTALL | re.IGNORECASE):
        try:
            obj = json.loads(match.group(1))
            if isinstance(obj, dict) and "name" in obj:
                tool_calls.append(obj)
        except Exception:
            pass

    if not tool_calls:
        try:
            start = text.find("{")
            if start != -1:
                depth = 0
                end = start
                for i, ch in enumerate(text[start:], start):
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                candidate = text[start:end]
                obj = json.loads(candidate)
                if isinstance(obj, dict) and "name" in obj:
                    tool_calls.append(obj)
        except Exception:
            pass

    if not tool_calls:
        for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
            try:
                obj = json.loads(match.group(1))
                if isinstance(obj, dict) and "name" in obj:
                    tool_calls.append(obj)
            except Exception:
                pass

    return tool_calls


def _ollama_connect_error() -> str:
    return (
        "[red]Cannot connect to Ollama.[/red]\n\n"
        "Make sure Ollama is running:\n"
        "  1. Open a terminal and run: [bold]ollama serve[/bold]\n"
        "  2. Or start it as a service: [bold]systemctl --user start ollama[/bold]\n"
        "  3. Verify with: [bold]ollama list[/bold]\n\n"
        "If Ollama uses a non-default port, set: [bold]export OLLAMA_BASE_URL=http://host:port[/bold]"
    )


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5-coder:latest", timeout: int = 300):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = 3
        self.client = httpx.AsyncClient(timeout=float(timeout))

    async def _request_with_retry(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_error = None
        for attempt in range(self.max_retries):
            try:
                resp = await self.client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    import asyncio
                    console.print(f"[dim]Connection attempt {attempt + 1} failed, retrying...[/dim]")
                    await asyncio.sleep(1 * (attempt + 1))
                continue
            except httpx.HTTPStatusError:
                raise
        raise last_error or httpx.ConnectError("Max retries exceeded")

    async def health_check(self) -> bool:
        """Check if Ollama is reachable and responsive."""
        try:
            resp = await self.client.get(f"{self.base_url}", timeout=5.0)
            return resp.status_code < 500
        except Exception:
            return False

    async def get_version(self) -> str:
        """Get Ollama version string."""
        try:
            resp = await self.client.get(f"{self.base_url}/api/version", timeout=5.0)
            resp.raise_for_status()
            return resp.json().get("version", "unknown")
        except Exception:
            return "unknown"

    async def list_models(self) -> list[dict[str, Any]]:
        try:
            resp = await self._request_with_retry("GET", f"{self.base_url}/api/tags")
            data = resp.json()
            return data.get("models", [])
        except (httpx.ConnectError, httpx.TimeoutException):
            console.print(Panel(_ollama_connect_error(), title="Connection Error", border_style="red"))
            return []
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Ollama returned HTTP {e.response.status_code}:[/red] {e.response.text[:200]}")
            return []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        stream: bool = True,
        temperature: float = 0.1,
        extra_options: Optional[dict[str, Any]] = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        options: dict[str, Any] = {"temperature": temperature}
        if extra_options:
            options.update(extra_options)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "options": options,
        }
        if tools:
            payload["tools"] = tools

        url = f"{self.base_url}/api/chat"
        full_text = ""

        try:
            if stream:
                async with self.client.stream("POST", url, json=payload) as resp:
                    if resp.status_code == 400 and tools:
                        yield {"type": "error", "data": "MODEL_DOES_NOT_SUPPORT_TOOLS"}
                        return
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            msg = data.get("message", {})
                            content = msg.get("content", "") or ""

                            if content:
                                full_text += content
                                yield {"type": "token", "data": content}

                            if msg.get("tool_calls"):
                                for tc in msg["tool_calls"]:
                                    yield {"type": "tool_call", "data": tc}

                            if data.get("done"):
                                if not msg.get("tool_calls"):
                                    fallback = _parse_tool_call_fallback(full_text)
                                    for tc in fallback:
                                        yield {"type": "tool_call", "data": tc}

                                yield {
                                    "type": "done",
                                    "content": full_text,
                                    "tool_calls": msg.get("tool_calls") or [],
                                }
                                return
                        except json.JSONDecodeError:
                            continue
            else:
                resp = await self.client.post(url, json=payload)
                if resp.status_code == 400 and tools:
                    yield {"type": "error", "data": "MODEL_DOES_NOT_SUPPORT_TOOLS"}
                    return
                resp.raise_for_status()
                data = resp.json()
                msg = data.get("message", {})
                content = msg.get("content", "") or ""
                tool_calls = msg.get("tool_calls", []) or []

                if content:
                    yield {"type": "token", "data": content}
                for tc in tool_calls:
                    yield {"type": "tool_call", "data": tc}

                if not tool_calls:
                    for tc in _parse_tool_call_fallback(content):
                        yield {"type": "tool_call", "data": tc}

                yield {"type": "done", "content": content, "tool_calls": tool_calls}

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and tools:
                yield {"type": "error", "data": "MODEL_DOES_NOT_SUPPORT_TOOLS"}
            else:
                yield {"type": "error", "data": str(e)}
        except Exception as e:
            yield {"type": "error", "data": str(e)}

    async def close(self):
        await self.client.aclose()