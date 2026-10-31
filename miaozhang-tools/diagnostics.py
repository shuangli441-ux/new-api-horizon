from __future__ import annotations

import math
import re
from typing import Any

import profitability as profit

TOKENS = ("cost", "price", "profit", "gross", "purchase", "avg")


def _flatten(obj: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            name = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.extend(_flatten(v, name))
            elif not isinstance(v, (list, tuple)):
                out.append((name, v))
    return out


def _number(v: Any) -> float | None:
    if v in (None, "", "-") or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        n = float(v)
        return n if math.isfinite(n) else None
    s = str(v).replace(",", "").replace("¥", "").replace("￥", "").strip()
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        return None
    try:
        n = float(s)
        return n if math.isfinite(n) else None
    except Exception:
        return None


def cost_schema(start: str, end: str) -> dict[str, Any]:
    orders = profit._flow_orders("sales", start, end)
    stats: dict[str, dict[str, Any]] = {}
    detail_rows = 0
    for order in orders:
        for d in order.get("detailVOs") or []:
            detail_rows += 1
            for path, value in _flatten(d):
                low = path.lower()
                if not any(t in low for t in TOKENS):
                    continue
                s = stats.setdefault(path, {"present": 0, "numeric": 0, "nonzero": 0, "sum": 0.0, "min": None, "max": None})
                if value not in (None, ""):
                    s["present"] += 1
                n = _number(value)
                if n is None:
                    continue
                s["numeric"] += 1
                s["nonzero"] += int(abs(n) > 1e-12)
                s["sum"] += n
                s["min"] = n if s["min"] is None else min(s["min"], n)
                s["max"] = n if s["max"] is None else max(s["max"], n)

    fields = []
    for path, s in stats.items():
        fields.append({
            "field": path,
            "present": s["present"],
            "numeric": s["numeric"],
            "nonzero": s["nonzero"],
            "sum": round(s["sum"], 4),
            "min": None if s["min"] is None else round(s["min"], 4),
            "max": None if s["max"] is None else round(s["max"], 4),
        })
    fields.sort(key=lambda x: (x["nonzero"], x["present"]), reverse=True)
    return {
        "scope": {"start": start, "end": end},
        "orders": len(orders),
        "detail_rows": detail_rows,
        "candidate_fields": fields,
        "privacy": "仅返回字段名和聚合统计，不返回客户、商品、单号或单条业务值。",
    }
