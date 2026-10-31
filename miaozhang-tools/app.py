from __future__ import annotations

from typing import Any

import diagnostics as diag
import legacy_app as legacy
import match_diagnostics as matchdiag
import product_summary as summary
import profitability as profit
import reference_cost as reference
from fastapi import Header

app = legacy.app
app.title = "Miaozhang Read Tool Service"
app.version = "1.2.4"

_REPLACED = {"/health", "/tools/overview", "/tools/profitability", "/tools/purchases", "/tools/inventory", "/tools/products", "/tools/quality", "/tools/cost-diagnostics", "/tools/product-summary-check", "/tools/reference-cost", "/tools/match-diagnostics"}
app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) not in _REPLACED]


def _enabled(name: str) -> bool:
    return str(legacy.os.getenv(name, "0")).strip().lower() in {"1", "true", "yes", "on"}


def _diag_scope() -> tuple[str, str]:
    return str(legacy.os.getenv("MZ_DIAG_START", "2026-10-01")), str(legacy.os.getenv("MZ_DIAG_END", "2026-10-31"))


@app.on_event("startup")
def startup_cost_diag() -> None:
    if not _enabled("MZ_STARTUP_COST_DIAG"): return
    start, end = _diag_scope()
    try:
        result = diag.cost_schema(start, end); print("MZ_COST_DIAG=PASS", flush=True); print("MZ_COST_DIAG_RESULT=" + legacy.json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
    except Exception as exc: print("MZ_COST_DIAG=FAIL:" + exc.__class__.__name__ + ":" + str(exc), flush=True)


@app.on_event("startup")
def startup_product_summary_diag() -> None:
    if not _enabled("MZ_STARTUP_SUMMARY_DIAG"): return
    start, end = _diag_scope()
    try:
        result = summary.fetch(start, end); print("MZ_SUMMARY_DIAG=PASS", flush=True); print("MZ_SUMMARY_DIAG_RESULT=" + legacy.json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
    except Exception as exc: print("MZ_SUMMARY_DIAG=FAIL:" + exc.__class__.__name__ + ":" + str(exc), flush=True)


@app.on_event("startup")
def startup_reference_cost_diag() -> None:
    if not _enabled("MZ_STARTUP_REFERENCE_DIAG"): return
    start, end = _diag_scope(); days = int(legacy.os.getenv("MZ_REFERENCE_LOOKBACK_DAYS", "365"))
    try:
        result = reference.historical_reference(start, end, days); print("MZ_REFERENCE_DIAG=PASS", flush=True); print("MZ_REFERENCE_DIAG_RESULT=" + legacy.json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
    except Exception as exc: print("MZ_REFERENCE_DIAG=FAIL:" + exc.__class__.__name__ + ":" + str(exc), flush=True)


@app.on_event("startup")
def startup_match_diag() -> None:
    if not _enabled("MZ_STARTUP_MATCH_DIAG"): return
    start, end = _diag_scope(); days = int(legacy.os.getenv("MZ_REFERENCE_LOOKBACK_DAYS", "365"))
    try:
        result = matchdiag.diagnose(start, end, days); print("MZ_MATCH_DIAG=PASS", flush=True); print("MZ_MATCH_DIAG_RESULT=" + legacy.json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
    except Exception as exc: print("MZ_MATCH_DIAG=FAIL:" + exc.__class__.__name__ + ":" + str(exc), flush=True)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "miaozhang-tool-service", "version": "1.2.4", "credentials_configured": bool(legacy.os.getenv("MZ_USERNAME") and legacy.os.getenv("MZ_PASSWORD")), "expected_owner_configured": bool(legacy.os.getenv("MZ_EXPECTED_OWNER_ID")), "expenses_complete": profit._bool_env("MZ_EXPENSES_COMPLETE", False), "read_only": True, "profit_guard": "enabled", "tools": ["overview", "profitability", "purchases", "inventory", "receivables", "payables", "cash", "products", "quality"], "admin_tools": ["cost-diagnostics", "product-summary-check", "reference-cost", "match-diagnostics"]}

@app.post("/tools/overview")
def overview(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end); return profit.overview(start, end)

@app.post("/tools/profitability")
def profitability(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end); return profit.overview(start, end)

@app.post("/tools/purchases")
def purchases(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end); return profit.purchases(start, end, req.top_n)

@app.post("/tools/inventory")
def inventory(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); return profit.inventory_view(req.top_n)

@app.post("/tools/products")
def products(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end); return profit.products(start, end, req.top_n)

@app.post("/tools/quality")
def quality(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end); return profit.quality(start, end)

@app.post("/tools/cost-diagnostics")
def cost_diagnostics(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end); return diag.cost_schema(start, end)

@app.post("/tools/product-summary-check")
def product_summary_check(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end); return summary.fetch(start, end)

@app.post("/tools/reference-cost")
def reference_cost(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end); return reference.historical_reference(start, end, 365)

@app.post("/tools/match-diagnostics")
def match_diagnostics(req: legacy.ToolRequest, authorization: str | None = Header(default=None)):
    legacy._auth(authorization); start, end = legacy._scope(req.start, req.end); return matchdiag.diagnose(start, end, 365)
