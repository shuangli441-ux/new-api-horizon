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
    purchase_ids_cost = {r.get("product_id") for r in purchases if r.get("product_id") is not None and float(r.get("unit_price") or 0) > 0}
    purchase_pairs_cost = {(r.get("product_id"), r.get("unit_id")) for r in purchases if r.get("product_id") is not None and r.get("unit_id") is not None and float(r.get("unit_price") or 0) > 0}

    inventory_ids = {r.get("product_id") for r in inv if r.get("product_id") is not None}
    inventory_pairs = {(r.get("product_id"), r.get("unit_id")) for r in inv if r.get("product_id") is not None and r.get("unit_id") is not None}
    inventory_ids_cost = {r.get("product_id") for r in inv if r.get("product_id") is not None and float(r.get("avg_cost") or 0) > 0}
    inventory_pairs_cost = {(r.get("product_id"), r.get("unit_id")) for r in inv if r.get("product_id") is not None and r.get("unit_id") is not None and float(r.get("avg_cost") or 0) > 0}
    inventory_pairs_usable = {(r.get("product_id"), r.get("unit_id")) for r in inv if r.get("product_id") is not None and r.get("unit_id") is not None and float(r.get("avg_cost") or 0) > 0 and float(r.get("qty") or 0) > 0}

    purchase_names = {_norm_name(r.get("product")) for r in purchases if _norm_name(r.get("product"))}
    purchase_names_cost = {_norm_name(r.get("product")) for r in purchases if _norm_name(r.get("product")) and float(r.get("unit_price") or 0) > 0}
    inventory_names = {_norm_name(r.get("product")) for r in inv if _norm_name(r.get("product"))}
    inventory_names_cost = {_norm_name(r.get("product")) for r in inv if _norm_name(r.get("product")) and float(r.get("avg_cost") or 0) > 0}

    stats = {
        "suspicious_rows": len(suspicious),
        "sales_with_product_id": sum(1 for r in suspicious if r.get("product_id") is not None),
        "sales_with_unit_id": sum(1 for r in suspicious if r.get("unit_id") is not None),
        "purchase_product_id_match": sum(1 for r in suspicious if r.get("product_id") in purchase_ids),
        "purchase_product_id_positive_price_match": sum(1 for r in suspicious if r.get("product_id") in purchase_ids_cost),
        "purchase_product_unit_match": sum(1 for r in suspicious if (r.get("product_id"), r.get("unit_id")) in purchase_pairs),
        "purchase_product_unit_positive_price_match": sum(1 for r in suspicious if (r.get("product_id"), r.get("unit_id")) in purchase_pairs_cost),
        "inventory_product_id_match": sum(1 for r in suspicious if r.get("product_id") in inventory_ids),
        "inventory_product_id_positive_cost_match": sum(1 for r in suspicious if r.get("product_id") in inventory_ids_cost),
        "inventory_product_unit_match": sum(1 for r in suspicious if (r.get("product_id"), r.get("unit_id")) in inventory_pairs),
        "inventory_product_unit_positive_cost_match": sum(1 for r in suspicious if (r.get("product_id"), r.get("unit_id")) in inventory_pairs_cost),
        "inventory_product_unit_usable_match": sum(1 for r in suspicious if (r.get("product_id"), r.get("unit_id")) in inventory_pairs_usable),
        "purchase_name_match": sum(1 for r in suspicious if _norm_name(r.get("product")) in purchase_names),
        "purchase_name_positive_price_match": sum(1 for r in suspicious if _norm_name(r.get("product")) in purchase_names_cost),
        "inventory_name_match": sum(1 for r in suspicious if _norm_name(r.get("product")) in inventory_names),
        "inventory_name_positive_cost_match": sum(1 for r in suspicious if _norm_name(r.get("product")) in inventory_names_cost),
    }
    return {
        "scope": {"start": start, "end": end},
        "history_start": history_start,
        "stats": stats,
        "privacy": "仅返回匹配数量，不返回商品名称、ID、客户或单据。",
    }
