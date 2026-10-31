from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import profitability as profit


def _norm_name(v: Any) -> str:
    return "".join(str(v or "").strip().lower().split())


def diagnose(start: str, end: str, lookback_days: int = 365) -> dict[str, Any]:
    history_start = (date.fromisoformat(start) - timedelta(days=lookback_days)).isoformat()
    sales = profit.flow("sales", start, end)
    purchases = profit.flow("purchase", history_start, end)
    inv = profit.inventory()
    suspicious = [r for r in sales if profit._is_cost_suspicious(r)]

    purchase_ids = {r.get("product_id") for r in purchases if r.get("product_id") is not None}
    purchase_pairs = {(r.get("product_id"), r.get("unit_id")) for r in purchases if r.get("product_id") is not None and r.get("unit_id") is not None}
    inventory_ids = {r.get("product_id") for r in inv if r.get("product_id") is not None}
    inventory_pairs = {(r.get("product_id"), r.get("unit_id")) for r in inv if r.get("product_id") is not None and r.get("unit_id") is not None}

    purchase_names = {_norm_name(r.get("product")) for r in purchases if _norm_name(r.get("product"))}
    inventory_names = {_norm_name(r.get("product")) for r in inv if _norm_name(r.get("product"))}

    stats = {
        "suspicious_rows": len(suspicious),
        "sales_with_product_id": sum(1 for r in suspicious if r.get("product_id") is not None),
        "sales_with_unit_id": sum(1 for r in suspicious if r.get("unit_id") is not None),
        "purchase_product_id_match": sum(1 for r in suspicious if r.get("product_id") in purchase_ids),
        "purchase_product_unit_match": sum(1 for r in suspicious if (r.get("product_id"), r.get("unit_id")) in purchase_pairs),
        "inventory_product_id_match": sum(1 for r in suspicious if r.get("product_id") in inventory_ids),
        "inventory_product_unit_match": sum(1 for r in suspicious if (r.get("product_id"), r.get("unit_id")) in inventory_pairs),
        "purchase_name_match": sum(1 for r in suspicious if _norm_name(r.get("product")) in purchase_names),
        "inventory_name_match": sum(1 for r in suspicious if _norm_name(r.get("product")) in inventory_names),
    }
    return {
        "scope": {"start": start, "end": end},
        "history_start": history_start,
        "stats": stats,
        "privacy": "仅返回匹配数量，不返回商品名称、ID、客户或单据。",
    }
