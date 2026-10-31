from __future__ import annotations

from typing import Any

import match_diagnostics as matchdiag
import product_summary as summary
import profitability as core


def _safe_call(fn, *args):
    try:
        return {"ok": True, "data": fn(*args)}
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__}


def analyze(start: str, end: str) -> dict[str, Any]:
    result = core.overview(start, end)

    sales = float(result.get("sales_amount") or 0)
    purchases = float(result.get("purchase_amount") or 0)
    inventory = float(result.get("inventory_amount") or 0)
    receivables = float(result.get("receivables") or 0)
    payables = float(result.get("payables") or 0)
    cash = result.get("cash") or {}

    result["operating_signals"] = {
        "purchase_to_sales_ratio": None if sales <= 0 else round(purchases / sales, 2),
        "inventory_to_period_sales_ratio": None if sales <= 0 else round(inventory / sales, 2),
        "net_operating_working_capital": round(inventory + receivables - payables, 2),
        "cash_balance_negative": float(cash.get("account_balance") or 0) < 0,
        "period_cash_outflow": float(cash.get("period_net_cash") or 0) < 0,
        "note": "这些是经营信号，不自动证明因果。采购/库存与销售比例受备货、淡旺季和历史库存影响。",
    }

    if result.get("profit_verdict") != "data_anomaly":
        result["cost_root_cause"] = "none_detected"
        result["repair_plan"] = []
        return result

    summary_check = _safe_call(summary.fetch, start, end)
    match_check = _safe_call(matchdiag.diagnose, start, end, 365)
    result["cost_cross_checks"] = {
        "product_sales_summary": summary_check,
        "reference_match_diagnostics": match_check,
    }

    root = "cost_data_incomplete"
    explanation = "销售成本异常，成本源数据覆盖不足。"
    stats = ((match_check.get("data") or {}).get("stats") or {}) if match_check.get("ok") else {}
    summary_data = summary_check.get("data") or {}

    no_positive_reference = bool(stats) and (
        int(stats.get("purchase_product_id_positive_price_match") or 0) == 0
        and int(stats.get("inventory_product_id_positive_cost_match") or 0) == 0
    )
    independent_summary_bad = summary_check.get("ok") and not bool(summary_data.get("plausible_for_profit"))

    if no_positive_reference and independent_summary_bad:
        root = "source_cost_missing_or_zero"
        explanation = "销售流水与商品销售汇总两套服务端报表都显示成本异常；匹配到的历史采购/库存记录也没有可用正数成本，说明源成本数据缺失或为零。"
    elif independent_summary_bad:
        root = "server_cost_reports_abnormal"
        explanation = "销售流水和商品销售汇总均显示异常高毛利，服务端成本口径本身需要修复。"
    elif summary_check.get("ok") and bool(summary_data.get("plausible_for_profit")):
        root = "cross_report_conflict"
        explanation = "销售流水成本异常，但商品销售汇总成本看起来可用；需要先做跨报表对账，不能直接选一个口径。"

    result["cost_root_cause"] = root
    result["cost_root_cause_explanation"] = explanation
    result["repair_plan"] = [
        {"priority": 1, "action": "补齐异常销售商品的真实成本来源", "detail": "优先补历史采购价/期初成本/库存均价；若启用批次管理则补批次成本。"},
        {"priority": 2, "action": "处理负库存与零成本库存", "detail": "负库存会破坏移动平均/库存成本；正库存零成本会继续高估毛利。"},
        {"priority": 3, "action": "修复后重新跑利润质量门", "detail": "要求销售零/负成本行归零，异常毛利通过校验，并与商品销售汇总交叉一致。"},
        {"priority": 4, "action": "确认费用完整性", "detail": "房租、工资、税费等未确认完整前，只能判断商品毛利/系统经营利润，不能称最终净利润。"},
    ]
    result["profit_readiness"] = {
        "ready": False,
        "blocked_by": ["sales_cost_quality", "expense_completeness"],
        "ready_when": [
            "销售零/负成本异常清零",
            "异常毛利率校验通过",
            "独立商品销售汇总与销售流水成本口径一致",
            "若要判断最终净利润，费用完整性必须明确确认",
        ],
    }
    return result
