from __future__ import annotations

import hmac
import json
import os
from typing import Any

import requests
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Miaozhang Public Agent", version="2.0.1")

MODEL_URL = os.getenv("MZ_MODEL_API_URL", "https://api.deepseek.com/chat/completions")
MODEL_NAME = os.getenv("MZ_MODEL_NAME", "deepseek-flash")
MODEL_PROBE = {"attempted": False, "live": False, "status": None}


class AgentRequest(BaseModel):
    task: str
    session_id: str = "mobile"


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


def _model(messages: list[dict[str, str]], max_tokens: int = 1200) -> str:
    key = str(os.getenv("MZ_MODEL_API_KEY", "") or "")
    if not key:
        raise HTTPException(status_code=503, detail="model key not configured")
    payload = {
        "model": os.getenv("MZ_MODEL_NAME", MODEL_NAME),
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    resp = requests.post(
        os.getenv("MZ_MODEL_API_URL", MODEL_URL),
        json=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        timeout=45,
    )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"model upstream HTTP {resp.status_code}")
    data = resp.json()
    return str((((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or "").strip()


def _tool_map() -> dict[str, str]:
    raw = str(os.getenv("MZ_TOOL_MAP", "") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): str(v) for k, v in data.items() if str(v).startswith("https://")}
    except Exception:
        return {}


def _call_tool(name: str, params: dict[str, Any]) -> dict[str, Any]:
    tools = _tool_map()
    url = tools.get(name)
    if not url:
        return {"ok": False, "tool": name, "error": "tool_not_configured"}
    token = str(os.getenv("MZ_TOOL_TOKEN", "") or "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.post(url, json=params, headers=headers, timeout=45)
        if resp.status_code >= 400:
            return {"ok": False, "tool": name, "status": resp.status_code}
        return {"ok": True, "tool": name, "data": resp.json()}
    except Exception:
        return {"ok": False, "tool": name, "error": "tool_request_failed"}


READ_TOOLS = {
    "overview": "经营总览：销售、成本、毛利、费用、利润",
    "purchases": "采购与供应商分析",
    "inventory": "库存、压货、缺货和周转",
    "receivables": "应收欠款与客户风险",
    "payables": "应付欠款与供应商压力",
    "cash": "现金与收付款",
    "products": "商品销售、毛利、亏损与热卖",
    "quality": "数据质量和异常",
}

WRITE_WORDS = ("开单", "新增", "创建", "删除", "修改", "导入", "上传", "付款", "收款登记", "库存调整", "权限")


@app.on_event("startup")
def startup_probe() -> None:
    if not os.getenv("MZ_MODEL_API_KEY"):
        return
    MODEL_PROBE["attempted"] = True
    try:
        text = _model([
            {"role": "system", "content": "连接测试，只回答 OK。"},
            {"role": "user", "content": "OK"},
        ], max_tokens=8)
        MODEL_PROBE["live"] = bool(text)
        MODEL_PROBE["status"] = "ok" if text else "empty"
    except HTTPException as exc:
        MODEL_PROBE["live"] = False
        MODEL_PROBE["status"] = f"upstream_{exc.status_code}"
    except Exception:
        MODEL_PROBE["live"] = False
        MODEL_PROBE["status"] = "request_failed"


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "miaozhang-public-agent",
        "version": "2.0.1",
        "model_provider": os.getenv("MZ_MODEL_PROVIDER", "deepseek"),
        "model_configured": bool(os.getenv("MZ_MODEL_API_KEY")),
        "model_probe": MODEL_PROBE,
        "configured_tools": sorted(_tool_map()),
        "write_enabled": False,
    }


@app.post("/v1/model/test")
def model_test(body: ModelTestRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _auth(authorization)
    text = _model([
        {"role": "system", "content": "你是连接测试助手，严格按用户要求简短回答。"},
        {"role": "user", "content": body.prompt[:1000]},
    ], max_tokens=64)
    return {"ok": True, "model": os.getenv("MZ_MODEL_NAME", MODEL_NAME), "text": text[:500]}


@app.post("/v1/agent")
def agent(body: AgentRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _auth(authorization)
    task = body.task.strip()
    if not task:
        raise HTTPException(status_code=400, detail="task required")
    if any(word in task for word in WRITE_WORDS):
        return {
            "ok": False,
            "requires_approval": True,
            "message": "写操作默认禁止直接执行；需先预演并人工审批。",
        }

    system = (
        "你是秒账经营智能体规划器。只输出JSON，不要Markdown。"
        "只能从给定read_tools中选择工具，不得编造工具。"
        "根据用户经营问题选择1到5个必要工具。"
        "JSON格式：{\"tools\":[{\"name\":\"overview\",\"params\":{}}],\"goal\":\"...\"}。"
    )
    plan_text = _model([
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps({"task": task, "read_tools": READ_TOOLS}, ensure_ascii=False)},
    ])
    try:
        start = plan_text.find("{")
        end = plan_text.rfind("}") + 1
        plan = json.loads(plan_text[start:end])
    except Exception:
        plan = {"tools": [{"name": "overview", "params": {}}], "goal": task}

    results = []
    for item in (plan.get("tools") or [])[:5]:
        name = str((item or {}).get("name") or "")
        if name not in READ_TOOLS:
            continue
        params = dict((item or {}).get("params") or {})
        results.append(_call_tool(name, params))

    if results and all(x.get("ok") for x in results):
        answer = _model([
            {"role": "system", "content": "你是经营分析助手。只依据工具数据回答；先结论，再证据，再风险。必须区分毛利、经营利润和现金，不得编造数字。"},
            {"role": "user", "content": json.dumps({"task": task, "results": results}, ensure_ascii=False, default=str)},
        ], max_tokens=1600)
        return {"ok": True, "plan": plan, "results": results, "answer": answer}

    return {
        "ok": True,
        "plan": plan,
        "results": results,
        "answer": "模型规划已完成；当前秒账读取工具尚未配置到公开部署壳，因此没有编造经营数据。",
        "tool_configuration_required": True,
    }
