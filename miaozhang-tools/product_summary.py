from __future__ import annotations

import json
from typing import Any

import legacy_app as base


def _page_property() -> Any:
    base.MZ.ensure()
    owner = base.MZ._call("GET", "/crm/owner/get", retries=1) or {}
    props = owner.get("pagePropertyList") or []
    for p in props:
        if isinstance(p, dict) and "prodSalesOverviewGrid" in p:
            return p
        if isinstance(p, str) and "prodSalesOverviewGrid" in p:
            try:
                return json.loads(p)
            except Exception:
                return p
    raise RuntimeError("product_summary_page_property_missing")


def _body(start: str, end: str, page: int, prop: Any) -> dict[str, Any]:
    return {
        "showInventoryFlag": True,
        "pageNum": page,
        "pageSize": 100,
        "beginDate": start,
        "endDate": end,
        "prodWHIds": [],
        "branchIds": [],
        "sortList": [{"sortColumn": "ratio", "sortOrder": "desc"}],
        "filingFlag": False,
        "prodFilingFlag": False,
        "type": "salesAmt",
        "subproductFlag": False,
        "showNegativeProfitFlag": False,
        "showZeroAvgPriceFlag": False,
        "isGift": False,
        "pagePropertyJson": prop,
    }


def fetch(start: str, end: str, max_pages: int = 500) -> dict[str, Any]:
    prop = _page_property()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    last_body = None
    total_rows = 0
    for page in range(max_pages):
        body = _body(start, end, page, prop)
        last_body = body
        data = base.MZ.post("/report/summary/productSales/pageList", body) or {}
        items = data.get("detailVOs")
        if not isinstance(items, list):
            raise RuntimeError("product_summary_structure_error")
        if not items:
            break
        sig = json.dumps(items, sort_keys=True, ensure_ascii=False)
        if sig in seen:
            raise RuntimeError("product_summary_page_repeated")
        seen.add(sig)
        rows.extend(items)
        total_rows = int(data.get("totalRows") or total_rows or 0)
        if total_rows and len(rows) >= total_rows:
            break
    else:
        raise RuntimeError("product_summary_pagination_limit")

    if last_body is None:
        last_body = _body(start, end, 0, prop)
    total_data = base.MZ.post("/report/summary/productSales/total", last_body) or {}
    total = total_data.get("total") or {}

    sales = sum(base._f(r.get("rawTotalAmt")) for r in rows)
    gross = sum(base._f(r.get("rawGrossProfitAmt")) for r in rows)
    cost = sales - gross
    server_sales = None if total.get("rawTotalAmt") in (None, "") else base._f(total.get("rawTotalAmt"))
    server_gross = None if total.get("rawGrossProfitAmt") in (None, "") else base._f(total.get("rawGrossProfitAmt"))

    if server_sales is not None and abs(sales - server_sales) > 0.02:
        raise RuntimeError("product_summary_sales_total_mismatch")

    margin = None if not sales else gross / sales
    plausible = bool(sales > 0 and cost > 0 and margin is not None and -0.50 <= margin <= 0.90)
    return {
        "scope": {"start": start, "end": end},
        "rows": len(rows),
        "sales_amount": round(sales, 2),
        "sales_cost": round(cost, 2),
        "gross_profit": round(gross, 2),
        "gross_margin": None if margin is None else round(margin, 4),
        "server_total_sales": None if server_sales is None else round(server_sales, 2),
        "server_total_gross": None if server_gross is None else round(server_gross, 2),
        "plausible_for_profit": plausible,
        "trace": "/report/summary/productSales/pageList + /total",
        "note": "商品销售汇总为独立服务端报表口径；只有销售额对账一致且成本/毛利通过异常阈值时，才允许用于利润交叉验证。",
    }
