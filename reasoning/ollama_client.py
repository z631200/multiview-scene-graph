"""Small standard-library Ollama client. No simulator or model SDK required."""

import base64
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, host="http://localhost:11434", model="gemma4:e4b",
                 timeout=600, options=None, thinking="auto"):
        if urlsplit(host).scheme not in ("http", "https"):
            raise ValueError("Ollama URL must use http or https")
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.options = options or {}
        self.thinking = thinking

    def request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.host + path, data=data,
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1500]
            raise OllamaError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise OllamaError(f"Ollama request failed at {self.host}: {exc}") from exc
        if not isinstance(result, dict) or result.get("error"):
            raise OllamaError(f"Invalid Ollama response: {result}")
        return result

    def preflight(self):
        version = self.request("/api/version")
        info = self.request("/api/show", {"model": self.model})
        if "vision" not in info.get("capabilities", []):
            raise OllamaError(f"{self.model} does not advertise vision support")
        tags = self.request("/api/tags")
        tag = next((m for m in tags.get("models", [])
                    if m.get("name") == self.model or m.get("model") == self.model), {})
        self.thinking_supported = "thinking" in info.get("capabilities", [])
        return {"version": version.get("version"), "model": self.model,
                "digest": tag.get("digest"), "details": info.get("details"),
                "capabilities": info.get("capabilities")}

    def chat(self, system, prompt, image=None, repair=None):
        user = {"role": "user", "content": prompt}
        if image is not None:
            user["images"] = [base64.b64encode(image).decode("ascii")]
        messages = [{"role": "system", "content": system}, user]
        if repair:
            messages.extend([
                {"role": "assistant", "content": repair[0]},
                {"role": "user", "content": repair[1]},
            ])
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "options": self.options, "keep_alive": "10m"}
        if getattr(self, "thinking_supported", False):
            payload["think"] = self.thinking == "on" or (self.thinking == "auto" and image is None)
        return self.request("/api/chat", payload)
