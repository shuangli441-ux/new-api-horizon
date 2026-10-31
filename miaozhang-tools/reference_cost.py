from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import profitability as profit


def historical_reference(start: str, end: str, lookback_days: int = 365) -> dict[str, Any]:
    start_date = date.fromisoformat(start)
    history_start = (start_date - timedelta(days=max(30, min(int(lookback_days), 1095)))).isoformat()
    sales = profit.flow("sales", start, end)
    purchases = profit.flow("purchase", history_start, end)
    inv = profit.inventory()
    result = profit.reconcile_cost(sales, purchases, inv)

    sales_amount = sum(float(x.get("sales_amount") or 0) for x in sales)
    estimate = result.get("reference_cost_estimate")
    coverage = float(result.get("reference_coverage") or 0)
    scenario = None
    if estimate is not None and sales_amount > 0 and coverage >= 0.80:
        estimate = float(estimate)
        scenario = {
            "status": "estimate_only",
            "sales_amount": round(sales_amount, 2),
            "reference_cost": round(estimate, 2),
            "reference_gross_profit": round(sales_amount - estimate, 2),
            "reference_gross_margin": round((sales_amount - estimate) / sales_amount, 4),
            "coverage": round(coverage, 4),
            "note": "使用历史最近采购价/当前库存均价补足异常成本，仅用于经营估算，不是已验证历史出库成本。",
        }

    return {
        "scope": {"start": start, "end": end},
        "history_start": history_start,
        "lookback_days": lookback_days,
        "sales_rows": len(sales),
        "purchase_reference_rows": len(purchases),
        "cost_quality": result,
        "reference_scenario": scenario,
        "safe_to_confirm_profit": False,
        "note": "历史采购价回溯只提高方向性估算覆盖率；正式利润仍优先使用真实销售成本/批次成本/移动加权成本。",
    }
