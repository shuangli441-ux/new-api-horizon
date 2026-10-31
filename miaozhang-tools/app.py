from __future__ import annotations

from typing import Any

import diagnostics as diag
import legacy_app as legacy
import profitability as profit
from fastapi import Header

app = legacy.app
app.title = "Miaozhang Read Tool Service"
app.version = "1.2.0"

_REPLACED = {"/health", "/tools/overview", "/tools/profitability", "/tools/purchases", "/tools/inventory", "/tools/products", "/tools/quality", "/tools/cost-diagnostics"}
app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) not in _REPLACED]


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "miaozhang-tool-service",
        "version": "1.2.0",
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
