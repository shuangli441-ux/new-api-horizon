from __future__ import annotations

from typing import Any

import diagnostics as diag
import legacy_app as legacy
import profitability as profit
from fastapi import Header

app = legacy.app
app.title = "Miaozhang Read Tool Service"
app.version = "1.2.1"

_REPLACED = {"/health", "/tools/overview", "/tools/profitability", "/tools/purchases", "/tools/inventory", "/tools/products", "/tools/quality", "/tools/cost-diagnostics"}
app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) not in _REPLACED]


@app.on_event("startup")
def startup_cost_diag() -> None:
    if str(legacy.os.getenv("MZ_STARTUP_COST_DIAG", "0")).strip().lower() not in {"1", "true", "yes", "on"}:
        return
    start = str(legacy.os.getenv("MZ_DIAG_START", "2026-10-01"))
    end = str(legacy.os.getenv("MZ_DIAG_END", "2026-10-31"))
    try:
        result = diag.cost_schema(start, end)
        print("MZ_COST_DIAG=PASS", flush=True)
        print("MZ_COST_DIAG_RESULT=" + legacy.json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
    except Exception as exc:
        print("MZ_COST_DIAG=FAIL:" + exc.__class__.__name__ + ":" + str(exc), flush=True)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "miaozhang-tool-service",
        "version": "1.2.1",
        "credentials_configured": bool(legacy.os.getenv("MZ_USERNAME") and legacy.os.getenv("MZ_PASSWORD")),
        "expected_owner_configured": bool(legacy.os.getenv("MZ_EXPECTED_OWNER_ID")),
        "expenses_complete": profit._bool_env("MZ_EXPENSES_COMPLETE", False),
        "read_only": True,
        "profit_guard": "enabled",
        "tools": ["overview", "profitability", "purchases", "inventory", "receivables", "payables", "cash", "products", "quality"],
        "admin_tools": ["cost-diagnostics"],
    }


@app.post("/tools/overview")
def overview(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end)
    return profit.overview(start, end)


@app.post("/tools/profitability")
def profitability(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end)
    return profit.overview(start, end)


@app.post("/tools/purchases")
def purchases(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end)
    return profit.purchases(start, end, req.top_n)


@app.post("/tools/inventory")
def inventory(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization)
    return profit.inventory_view(req.top_n)


@app.post("/tools/products")
def products(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end)
    return profit.products(start, end, req.top_n)


@app.post("/tools/quality")
def quality(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end)
    return profit.quality(start, end)


@app.post("/tools/cost-diagnostics")
def cost_diagnostics(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end)
    return diag.cost_schema(start, end)
