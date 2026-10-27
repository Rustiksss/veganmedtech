"""Bounded, fixed-origin HTTPS. No redirects, SDK, tools, or automatic retries."""
import http.client
import json
import math
import socket
import ssl
import time
from queue import Queue
from threading import Thread
from django.conf import settings

MAX_BYTES = 65536
TIMEOUT = 18


class ProviderError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)  # Never retain upstream bodies, credentials or exception text.


def complete(messages):
    """The caller's deadline also bounds OS DNS resolution, which ignores socket timeouts."""
    result = Queue(maxsize=1)
    deadline = time.monotonic() + TIMEOUT

    def work():
        try:
            result.put(_exchange(messages, deadline))
        except ProviderError as exc:
            result.put(exc)
        except Exception:
            result.put(ProviderError("unavailable"))

    worker = Thread(target=work, daemon=True)
    worker.start()
    worker.join(max(0, deadline - time.monotonic()))
    if worker.is_alive():
        raise ProviderError("timeout")
    value = result.get_nowait()
    if isinstance(value, ProviderError):
        raise value
    return value


def _exchange(messages, deadline):
    if not settings.POLZA_API_KEY:
        raise ProviderError("configuration")
    payload = {"model": settings.POLZA_MODEL, "messages": messages, "max_tokens": 512,
        "stream": False, "reasoning": {"effort": "none"},
        "provider": {"sort": "price", "max_price": {"prompt": 6, "completion": 12}}}
    if settings.POLZA_MODEL == "cohere/command-r7b-12-2024":
        payload = {"model": settings.POLZA_MODEL, "messages": messages, "max_tokens": 512,
            "stream": False, "temperature": 0,
            "provider": {"only": ["cohere"], "allow_fallbacks": False,
                "sort": "latency", "require_parameters": True,
                "max_price": {"prompt": 4.3, "completion": 17.2, "request": 0}}}
        if settings.ASSISTANT_ALERTING_MODE == "demo":
            payload["response_format"] = {"type": "json_object"}
    connection = http.client.HTTPSConnection("polza.ai", timeout=TIMEOUT, context=ssl.create_default_context())

    def budget(sock):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        sock.settimeout(remaining)

    try:
        connection.connect()
        sock = connection.sock
        budget(sock)
        connection.request("POST", "/api/v1/chat/completions", body=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + settings.POLZA_API_KEY, "Content-Type": "application/json"})
        budget(sock)
        response = connection.getresponse()
        if response.status != 200:
            raise ProviderError({401: "credentials", 402: "balance", 429: "rate_limit"}.get(response.status, "unavailable"))
        data = bytearray()
        while not response.isclosed():
            budget(sock)
            chunk = response.read1(min(8192, MAX_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise ProviderError("invalid_response")
        if response.length not in (None, 0):
            raise ProviderError("incomplete")
        result = json.loads(data)
        if not isinstance(result, dict) or not isinstance(result.get("choices"), list):
            raise ProviderError("invalid_response")
        choice = result["choices"][0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ProviderError("invalid_response")
        reply = choice["message"]["content"]
        if result.get("model") != settings.POLZA_MODEL:
            raise ProviderError("invalid_response")
        if choice.get("finish_reason") != "stop":
            raise ProviderError("incomplete")
        if not isinstance(reply, str) or not reply.strip() or len(reply) > 4096:
            raise ProviderError("invalid_response")
        # Only bounded accounting metadata, no upstream arbitrary objects or text.
        accounting = result.get("usage") or {}
        if not isinstance(accounting, dict):
            raise ProviderError("invalid_response")
        usage = {k: v for k, v in accounting.items()
                 if k in {"prompt_tokens", "completion_tokens", "total_tokens", "cost"}
                 and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0}
        return reply.strip(), usage
    except ProviderError:
        raise
    except (TimeoutError, socket.timeout):
        raise ProviderError("timeout") from None
    except (KeyError, IndexError, TypeError, ValueError, UnicodeError):
        raise ProviderError("invalid_response") from None
    except (OSError, http.client.HTTPException):
        raise ProviderError("unavailable") from None
    finally:
        connection.close()
