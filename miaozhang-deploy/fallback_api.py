from __future__ import annotations

import hmac
import os
from typing import Any

import requests
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Miaozhang Render Bootstrap", version="1.0.0")


class ModelTestRequest(BaseModel):
    prompt: str = "只回答 DEEPSEEK_OK"


def _auth(authorization: str | None) -> None:
    expected = str(os.getenv("MZ_EXECUTOR_KEY", "") or "")
    if not expected:
        return
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "miaozhang-render-bootstrap",
        "private_runtime_loaded": False,
        "deepseek_configured": bool(os.getenv("MZ_MODEL_API_KEY")),
        "private_repo_token_configured": bool(os.getenv("MZ_GITHUB_TOKEN")),
    }


@app.get("/v1/model/status")
def model_status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _auth(authorization)
    return {
        "provider": os.getenv("MZ_MODEL_PROVIDER", "deepseek"),
        "api_url": os.getenv("MZ_MODEL_API_URL", "https://api.deepseek.com/chat/completions"),
        "model": os.getenv("MZ_MODEL_NAME", "deepseek-flash"),
        "api_key_configured": bool(os.getenv("MZ_MODEL_API_KEY")),
    }


@app.post("/v1/model/test")
def model_test(body: ModelTestRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _auth(authorization)
    api_key = str(os.getenv("MZ_MODEL_API_KEY", "") or "")
    if not api_key:
        raise HTTPException(status_code=503, detail="model key not configured")
    url = os.getenv("MZ_MODEL_API_URL", "https://api.deepseek.com/chat/completions")
    model = os.getenv("MZ_MODEL_NAME", "deepseek-flash")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是连接测试助手。严格按用户要求简短回答。"},
            {"role": "user", "content": body.prompt[:1000]},
        ],
        "temperature": 0,
        "max_tokens": 64,
    }
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=30,
        )
        status = resp.status_code
        if status >= 400:
            return {"ok": False, "provider_http_status": status, "message": "model request failed"}
        data = resp.json()
        text = str((((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or "")
        return {"ok": True, "model": data.get("model") or model, "text": text[:500]}
    except requests.RequestException:
        return {"ok": False, "message": "model network request failed"}
    except Exception:
        return {"ok": False, "message": "model response parse failed"}
