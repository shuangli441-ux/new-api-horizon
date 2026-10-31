from __future__ import annotations

import hmac
import json
import os
from typing import Any

import requests
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Miaozhang Public Agent", version="2.1.1")

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
        "thinking": {"type": "disabled"},
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
        resp = requests.post(url, json=params, headers=headers, timeout=90)
        if resp.status_code >= 400:
            return {"ok": False, "tool": name, "status": resp.status_code}
        return {"ok": True, "tool": name, "data": resp.json()}
    except Exception:
        return {"ok": False, "tool": name, "error": "tool_request_failed"}


READ_TOOLS = {
    "overview": "经营总览：销售、采购、库存、应收、应付、现金和经营状态",
    "profitability": "盈利能力与利润可信度：成本质量门、毛利、费用完整性、利润结论",
    "purchases": "采购与供应商分析",
    "inventory": "库存、压货、缺货和周转",
    "receivables": "应收欠款与客户风险",
    "payables": "应付欠款与供应商压力",
    "cash": "现金与收付款",
    "products": "商品销售、毛利、亏损与热卖；成本异常商品不输出毛利",
    "quality": "数据质量、成本异常和利润可用性",
}

WRITE_WORDS = ("开单", "新增", "创建", "删除", "修改", "导入", "上传", "付款", "收款登记", "库存调整", "权限")
PROFIT_WORDS = ("赚不赚钱", "赚钱", "亏钱", "盈利", "利润", "毛利", "净利", "净利润", "利润率")


@app.on_event("startup")
def startup_probe() -> None:
    if not os.getenv("MZ_MODEL_API_KEY"):
        return
    MODEL_PROBE["attempted"] = True
    try:
        text = _model([
            {"role": "system", "content": "连接测试，只回答 OK。"},
            {"role": "user", "content": "OK"},
        ], max_tokens=16)
        MODEL_PROBE["live"] = bool(text)
        MODEL_PROBE["status"] = "ok" if text else "empty"
    except HTTPException as exc:
        MODEL_PROBE["live"] = False
        MODEL_PROBE["status"] = f"upstream_{exc.status_code}"
    except Exception:
        MODEL_PROBE["live"] = False
        MODEL_PROBE["status"] = "request_failed"


@app.on_event("startup")
def startup_profitability_probe() -> None:
    if str(os.getenv("MZ_STARTUP_PROFIT_PROBE", "0")).strip().lower() not in {"1", "true", "yes", "on"}:
        return
    start = str(os.getenv("MZ_PROBE_START", "2026-10-01"))
    end = str(os.getenv("MZ_PROBE_END", "2026-10-31"))
    result = _call_tool("profitability", {"start": start, "end": end, "top_n": 5})
    if not result.get("ok"):
        print("MZ_PROFIT_PROBE=FAIL:" + json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
        return
    data = result.get("data") or {}
    safe = {
        "scope": data.get("scope"),
        "profit_verdict": data.get("profit_verdict"),
        "profit_confidence": data.get("profit_confidence"),
        "conclusion": data.get("conclusion"),
        "sales_amount": data.get("sales_amount"),
        "sales_cost": data.get("sales_cost"),
        "gross_profit": data.get("gross_profit"),
        "gross_margin": data.get("gross_margin"),
        "operating_expense": data.get("operating_expense"),
        "operating_profit": data.get("operating_profit"),
        "inventory_amount": data.get("inventory_amount"),
        "receivables": data.get("receivables"),
        "payables": data.get("payables"),
        "cash_signal": data.get("cash_signal"),
        "cost_quality": data.get("cost_quality"),
        "data_quality": data.get("data_quality"),
        "expense_completeness": data.get("expense_completeness"),
        "reference_cost_scenario": data.get("reference_cost_scenario"),
        "raw_profit_metrics_quarantined": data.get("raw_profit_metrics_quarantined"),
    }
    print("MZ_PROFIT_PROBE=PASS", flush=True)
    print("MZ_PROFIT_PROBE_RESULT=" + json.dumps(safe, ensure_ascii=False, separators=(",", ":")), flush=True)
    try:
        answer = _model([
            {"role": "system", "content": "只依据提供的数据回答。若profit_verdict=data_anomaly，必须说暂不能确认赚不赚钱；不得把隔离原始利润当真实利润；参考成本情景必须明确称估算。用3到5句中文。"},
            {"role": "user", "content": json.dumps(safe, ensure_ascii=False, default=str)},
        ], max_tokens=360)
        print("MZ_PROFIT_PROBE_MODEL=" + json.dumps(answer, ensure_ascii=False), flush=True)
    except Exception as exc:
        print("MZ_PROFIT_PROBE_MODEL=FAIL:" + exc.__class__.__name__, flush=True)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "miaozhang-public-agent",
        "version": "2.1.1",
        "model_provider": os.getenv("MZ_MODEL_PROVIDER", "deepseek"),
        "model_configured": bool(os.getenv("MZ_MODEL_API_KEY")),
        "model_probe": MODEL_PROBE,
        "configured_tools": sorted(_tool_map()),
        "profit_guard": "enabled",
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


def _fallback_plan(task: str) -> dict[str, Any]:
    name = "profitability" if any(word in task for word in PROFIT_WORDS) else "overview"
    return {"tools": [{"name": name, "params": {}}], "goal": task}


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
        "只要用户询问赚钱、亏损、利润、毛利、净利或利润率，必须包含profitability工具。"
        "如果用户还问钱为什么变少，再加cash、inventory、receivables、payables中必要的工具。"
        "JSON格式：{\"tools\":[{\"name\":\"profitability\",\"params\":{}}],\"goal\":\"...\"}。"
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
        plan = _fallback_plan(task)

    if any(word in task for word in PROFIT_WORDS):
        tools = list(plan.get("tools") or [])
        if not any(str((x or {}).get("name") or "") == "profitability" for x in tools):
            tools.insert(0, {"name": "profitability", "params": {}})
        plan["tools"] = tools[:5]

    results = []
    for item in (plan.get("tools") or [])[:5]:
        name = str((item or {}).get("name") or "")
        if name not in READ_TOOLS:
            continue
        params = dict((item or {}).get("params") or {})
        results.append(_call_tool(name, params))

    if results and all(x.get("ok") for x in results):
        answer = _model([
            {
                "role": "system",
                "content": (
                    "你是经营分析助手。只依据工具数据回答；先结论，再证据，再风险。"
                    "必须区分商品毛利、经营利润和现金。"
                    "如果profit_verdict=data_anomaly，必须明确说暂不能确认赚不赚钱；"
                    "不得把raw_profit_metrics_quarantined中的数字当作真实利润。"
                    "reference_cost_scenario只能称为参考/估算情景，绝不能称为确认利润。"
                    "如果expense_completeness.confirmed=false，不得把系统经营利润称为最终净利润。"
                    "不得编造或补齐缺失数字。"
                ),
            },
            {"role": "user", "content": json.dumps({"task": task, "results": results}, ensure_ascii=False, default=str)},
        ], max_tokens=1600)
        return {"ok": True, "plan": plan, "results": results, "answer": answer}

    return {
        "ok": True,
        "plan": plan,
        "results": results,
        "answer": "模型规划已完成，但一个或多个秒账读取工具调用失败；没有编造经营数据。",
        "tool_configuration_required": True,
    }
