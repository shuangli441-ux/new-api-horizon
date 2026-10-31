from __future__ import annotations

import os
import threading

import requests
from fastapi import FastAPI

app = FastAPI(title="DeepSeek Smoke", version="1.0")
_state = {"done": False, "ok": False, "status": None, "model": None, "content": None, "error": None}
_lock = threading.Lock()


def _run_once():
    with _lock:
        if _state["done"]:
            return
        key = os.getenv("DEEPSEEK_API_KEY", "")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
        url = "https://api.deepseek.com/chat/completions"
        try:
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Reply with exactly DEEPSEEK_OK"},
                        {"role": "user", "content": "connectivity test"},
                    ],
                    "stream": False,
                    "max_tokens": 16,
                    "temperature": 0,
                },
                timeout=30,
            )
            data = r.json() if r.content else {}
            content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) if isinstance(data, dict) else None
            _state.update({
                "done": True,
                "ok": bool(r.ok and isinstance(content, str) and content.strip()),
                "status": r.status_code,
                "model": data.get("model") if isinstance(data, dict) else None,
                "content": content,
                "error": None if r.ok else (data.get("error") if isinstance(data, dict) else "request_failed"),
            })
        except Exception as exc:
            _state.update({"done": True, "ok": False, "error": type(exc).__name__})


@app.on_event("startup")
def startup():
    _run_once()


@app.get("/health")
def health():
    return {"ok": True, "smoke_done": _state["done"]}


@app.get("/result")
def result():
    return dict(_state)
