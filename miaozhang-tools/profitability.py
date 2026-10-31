from __future__ import annotations

import os
from datetime import date
from typing import Any

import legacy_app as base


def _bool_env(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _flow_orders(kind: str, start: str, end: str, page_size: int = 100, max_pages: int = 500) -> list[dict[str, Any]]:
    path = "/report/flow/sales/pageDetailList" if kind == "sales" else "/report/flow/purchase/pageDetailList"
    merged: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    detail_ids: dict[tuple[Any, Any, Any], set[Any]] = {}
    page_signatures: set[str] = set()

    for page in range(max_pages):
        data = base.MZ.post(path, base._flow_body(kind, start, end, page, page_size)) or {}
        orders: list[dict[str, Any]] = []
        for day in data.get("dateVOs") or []:
            orders.extend(day.get("orderVOs") or [])
        if not orders:
            return list(merged.values())

        sig = base.json.dumps(orders, sort_keys=True, ensure_ascii=False)
        if sig in page_signatures:
            raise RuntimeError("flow_page_repeated")
        page_signatures.add(sig)

        for order in orders:
            key = (order.get("orderId"), order.get("bizType"), order.get("orderNumber"))
            if key[0] is None:
                raise RuntimeError("flow_order_missing_id")
            if key not in merged:
                merged[key] = dict(order, detailVOs=[])
                detail_ids[key] = set()
            for d in order.get("detailVOs") or []:
                detail_id = d.get("id")
                if detail_id is not None:
                    if detail_id in detail_ids[key]:
                        continue
                    detail_ids[key].add(detail_id)
                merged[key]["detailVOs"].append(d)

    raise RuntimeError("flow_pagination_limit")


def flow(kind: str, start: str, end: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order in _flow_orders(kind, start, end):
        expected_biz = "salesOrder" if kind == "sales" else "purchaseOrder"
        if order.get("bizType") not in (None, expected_biz):
            continue
        summary = order.get("sum") or {}
        for d in order.get("detailVOs") or []:
            amt = base._f(d.get("rawTotalAmt") or d.get("fullRawTotalAmt"))
            common = {
                "date": order.get("date") or d.get("delyDate"),
                "product": d.get("productName") or "",
                "qty": base._f(d.get("qty")),
                "order_id": order.get("orderId"),
                "order_no": order.get("orderNumber"),
                "detail_id": d.get("id"),
                "product_id": d.get("productId") or d.get("prodId"),
                "unit_id": d.get("unitId") or d.get("prodUnitId"),
                "unit_rate": base._f(d.get("unitRate"), 1.0),
                "unpaid": base._f(summary.get("orderUnpaidAmt")),
            }
            if kind == "sales":
                gp_raw = d.get("rawGrossProfitAmt")
                gross = base._f(gp_raw, default=float("nan"))
                unit_cost = base._f(d.get("purchasePrice"))
                if base.math.isnan(gross):
                    gross = amt - base._f(d.get("qty")) * unit_cost
                cost = amt - gross
                rows.append({
                    **common,
                    "client": order.get("clientName") or "",
                    "sales_amount": amt,
                    "sales_cost": cost,
                    "gross_profit": gross,
                    "unit_cost": unit_cost,
                    "cost_source": "rawGrossProfitAmt" if gp_raw not in (None, "") else "qty*purchasePrice",
                })
            else:
                rows.append({
                    **common,
                    "vendor": order.get("clientName") or "",
                    "purchase_amount": amt,
                    "unit_price": base._f(d.get("purchasePrice")),
                })
    return rows


def inventory(page_size: int = 200, max_pages: int = 500) -> list[dict[str, Any]]:
    req = {
        "queryType": "inventory", "prodAvailable": True, "pageNum": 0, "pageSize": page_size,
        "showPositiveQty": True, "showNegativeAndZeroQty": True, "shoesHatsModuleFlag": False,
        "showQtyType": "qty", "sortList": [{"sortColumn": "createDate", "sortOrder": "desc"}],
        "filingFlag": False, "prodWHIds": [],
    }
    total = int(base.MZ.post("/prod/inventory/getTotal", dict(req)) or 0)
    out: list[dict[str, Any]] = []
    seen_pages: set[str] = set()
    for page in range(max_pages):
        body = dict(req); body["pageNum"] = page
        data = base.MZ.post("/prod/inventory/pageList", body) or {}
        items = (data.get("inventoryPageVo") or {}).get("list") or []
        if not items:
            break
        sig = base.json.dumps(items, sort_keys=True, ensure_ascii=False)
        if sig in seen_pages:
            raise RuntimeError("inventory_page_repeated")
        seen_pages.add(sig)
        out.extend(items)
        if total and len(out) >= total:
            break
    if total and len(out) != total:
        raise RuntimeError("inventory_incomplete")

    rows: list[dict[str, Any]] = []
    for r in out:
        avg = None
        exts = r.get("inventoryExtVOS") or []
        selected = [x for x in exts if x.get("unitId") == r.get("prodUnitId")]
        if not selected and len(exts) == 1:
            selected = exts
        for x in selected:
            if x.get("avgCost") not in (None, ""):
                avg = base._f(x.get("avgCost")); break
        if avg is None:
            avg = base._f(r.get("showAvgCost"))
        qty = base._f(r.get("qty"))
        rows.append({
            "product": r.get("prodName") or "",
            "product_id": r.get("prodId"),
            "unit_id": r.get("prodUnitId"),
            "qty": qty,
            "avg_cost": avg,
            "inventory_amount": qty * avg,
            "warehouse": r.get("prodWHName") or "",
            "inventory_id": r.get("id"),
            "available_qty": base._f(r.get("availableQty")),
            "warn_min": base._f(r.get("warnMinQty")),
            "warn_max": base._f(r.get("warnMaxQty")),
        })
    return rows


def _margin(revenue: float, cost: float) -> float | None:
    return None if not revenue else (revenue - cost) / revenue


def _is_cost_suspicious(row: dict[str, Any]) -> bool:
    revenue = float(row.get("sales_amount") or 0)
    cost = float(row.get("sales_cost") or 0)
    if revenue <= 0:
        return False
    margin = _margin(revenue, cost)
    return cost <= 0 or margin is None or margin > 0.90 or margin < -0.50


def _latest_purchase_map(purchases: list[dict[str, Any]]) -> dict[tuple[Any, Any], dict[str, Any]]:
    out: dict[tuple[Any, Any], dict[str, Any]] = {}
    for r in purchases:
        key = (r.get("product_id"), r.get("unit_id"))
        if None in key or float(r.get("unit_price") or 0) <= 0:
            continue
        old = out.get(key)
        if old is None or str(r.get("date") or "") >= str(old.get("date") or ""):
            out[key] = r
    return out


def _inventory_cost_map(inv: list[dict[str, Any]]) -> dict[tuple[Any, Any], float]:
    sums: dict[tuple[Any, Any], tuple[float, float]] = {}
    for r in inv:
        key = (r.get("product_id"), r.get("unit_id"))
        qty = float(r.get("qty") or 0)
        cost = float(r.get("avg_cost") or 0)
        if None in key or qty <= 0 or cost <= 0:
            continue
        amount, weight = sums.get(key, (0.0, 0.0))
        sums[key] = (amount + qty * cost, weight + qty)
    return {k: a / q for k, (a, q) in sums.items() if q > 0}


def reconcile_cost(sales: list[dict[str, Any]], purchases: list[dict[str, Any]], inv: list[dict[str, Any]]) -> dict[str, Any]:
    latest = _latest_purchase_map(purchases)
    inv_cost = _inventory_cost_map(inv)
    raw_total = 0.0
    reference_total = 0.0
    covered_revenue = 0.0
    total_revenue = 0.0
    suspicious_rows = 0
    zero_cost_rows = 0
    abnormal_margin_rows = 0
    reference_rows = 0
    reference_by_source = {"server": 0, "latest_purchase_exact_unit": 0, "inventory_avg_exact_unit": 0, "uncovered": 0}

    for r in sales:
        revenue = float(r.get("sales_amount") or 0)
        raw_cost = float(r.get("sales_cost") or 0)
        total_revenue += max(0.0, revenue)
        raw_total += raw_cost
        margin = _margin(revenue, raw_cost)
        if revenue > 0 and raw_cost <= 0:
            zero_cost_rows += 1
        if revenue > 0 and margin is not None and (margin > 0.90 or margin < -0.50):
            abnormal_margin_rows += 1

        if not _is_cost_suspicious(r):
            reference_total += raw_cost
            covered_revenue += max(0.0, revenue)
            reference_rows += 1
            reference_by_source["server"] += 1
            continue

        suspicious_rows += 1
        key = (r.get("product_id"), r.get("unit_id"))
        qty = abs(float(r.get("qty") or 0))
        candidate = None
        source = None
        p = latest.get(key)
        if p is not None and float(p.get("unit_price") or 0) > 0 and qty > 0:
            candidate = qty * float(p["unit_price"])
            source = "latest_purchase_exact_unit"
        elif key in inv_cost and inv_cost[key] > 0 and qty > 0:
            candidate = qty * inv_cost[key]
            source = "inventory_avg_exact_unit"

        if candidate is not None:
            reference_total += candidate
            covered_revenue += max(0.0, revenue)
            reference_rows += 1
            reference_by_source[source] += 1
        else:
            reference_by_source["uncovered"] += 1

    raw_margin = _margin(total_revenue, raw_total)
    reference_coverage = (covered_revenue / total_revenue) if total_revenue > 0 else 0.0
    severe = bool(
        zero_cost_rows > 0
        or (raw_margin is not None and raw_margin > 0.90)
        or abnormal_margin_rows >= max(1, int(len(sales) * 0.20))
    )
    return {
        "raw_cost": round(raw_total, 2),
        "raw_gross_margin": round(raw_margin, 4) if raw_margin is not None else None,
        "suspicious_rows": suspicious_rows,
        "zero_or_negative_cost_rows": zero_cost_rows,
        "abnormal_margin_rows": abnormal_margin_rows,
        "severe_anomaly": severe,
        "reference_cost_estimate": round(reference_total, 2) if reference_rows else None,
        "reference_coverage": round(reference_coverage, 4),
        "reference_rows": reference_rows,
        "reference_by_source": reference_by_source,
        "reference_note": "参考成本仅用于异常诊断；仅采用同产品ID+同单位ID的最新采购价或库存均价，不替代已验证历史销售成本。",
    }


def quality_report(sales: list[dict[str, Any]], inv: list[dict[str, Any]], expenses: list[dict[str, Any]], cost: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    def add(code: str, count: int, impact: str, deduction: int, severity: str = "warning") -> None:
        if count:
            issues.append({"code": code, "count": int(count), "impact": impact, "deduction": min(25, deduction), "severity": severity})

    add("sales_cost_zero_or_missing", cost["zero_or_negative_cost_rows"], "毛利会被高估，禁止直接判断盈利", 25, "critical")
    add("abnormal_gross_margin", cost["abnormal_margin_rows"], "单行毛利率>90%或<-50%，需核对成本口径", 15, "critical")
    add("negative_inventory", sum(1 for x in inv if float(x.get("qty") or 0) < 0), "库存金额和可售数量可能不可靠", 10)
    add("positive_inventory_zero_cost", sum(1 for x in inv if float(x.get("qty") or 0) > 0 and float(x.get("avg_cost") or 0) <= 0), "库存价值和成本参考可能偏低", 15)
    add("loss_sales_rows", sum(1 for x in sales if float(x.get("sales_amount") or 0) < float(x.get("sales_cost") or 0)), "存在亏损销售或成本异常", 5)
    add("unclassified_expense", sum(1 for x in expenses if not x.get("category") or x.get("category") == "未分类"), "费用结构不完整", 5)

    score = max(0, 100 - sum(x["deduction"] for x in issues))
    return {
        "score": score,
        "meaning": "规则体检评分，不是统计意义的准确率",
        "issues": issues,
        "profit_blocked": cost["severe_anomaly"],
    }


def overview(start: str, end: str) -> dict[str, Any]:
    sales = flow("sales", start, end)
    purchases = flow("purchase", start, end)
    expenses = base._expenses(start, end)
    inv = inventory()
    ar = base._receivables(end)
    ap = base._payables(end)
    cash = base._cash(start, end)

    sales_amt = sum(float(x.get("sales_amount") or 0) for x in sales)
    raw_sales_cost = sum(float(x.get("sales_cost") or 0) for x in sales)
    raw_gross = sales_amt - raw_sales_cost
    expense = sum(float(x.get("amount") or 0) for x in expenses)
    raw_profit = raw_gross - expense
    purchase_amt = sum(float(x.get("purchase_amount") or 0) for x in purchases)
    inv_amt = sum(float(x.get("inventory_amount") or 0) for x in inv)
    receivables = sum(float(x.get("amount") or 0) for x in ar)
    payables = sum(float(x.get("amount") or 0) for x in ap)

    cost = reconcile_cost(sales, purchases, inv)
    quality = quality_report(sales, inv, expenses, cost)
    expenses_complete = _bool_env("MZ_EXPENSES_COMPLETE", False)

    reference = None
    if cost.get("reference_cost_estimate") is not None and cost.get("reference_coverage", 0) >= 0.80:
        ref_cost = float(cost["reference_cost_estimate"])
        reference = {
            "status": "estimate_only",
            "coverage": cost["reference_coverage"],
            "sales_cost": round(ref_cost, 2),
            "gross_profit": round(sales_amt - ref_cost, 2),
            "gross_margin": round((sales_amt - ref_cost) / sales_amt, 4) if sales_amt else None,
            "operating_profit_after_recorded_expenses": round(sales_amt - ref_cost - expense, 2),
            "note": "仅用于方向性诊断，不是确认利润；参考成本不是历史批次/移动加权销售成本。",
        }

    if quality["profit_blocked"]:
        verdict = "data_anomaly"
        confidence = "low"
        conclusion = "销售成本口径异常，暂不能确认这个店赚不赚钱；先修成本数据，再判断利润。"
        gross_profit = gross_margin = operating_profit = operating_margin = None
    else:
        gross_profit = round(raw_gross, 2)
        gross_margin = round(raw_gross / sales_amt, 4) if sales_amt else None
        operating_profit = round(raw_profit, 2)
        operating_margin = round(raw_profit / sales_amt, 4) if sales_amt else None
        if raw_profit < 0:
            verdict = "system_operating_loss"
            confidence = "medium" if not expenses_complete else "high"
            conclusion = "按系统已记录成本和费用，本期经营利润为负。"
        elif expenses_complete:
            verdict = "confirmed_profitable" if raw_profit > 0 else "break_even"
            confidence = "high"
            conclusion = "成本与费用覆盖通过校验，可按当前经营口径判断盈利。" if raw_profit > 0 else "当前经营口径接近盈亏平衡。"
        else:
            verdict = "gross_profit_positive_net_unknown"
            confidence = "medium"
            conclusion = "商品毛利为正，但费用完整性未确认，暂不能把系统经营利润当作最终净利润。"

    cash_signal = {
        "account_balance": cash.get("account_balance"),
        "period_net_cash": cash.get("period_net_cash"),
        "negative_balance": (cash.get("account_balance") is not None and float(cash.get("account_balance")) < 0),
        "net_outflow": (cash.get("period_net_cash") is not None and float(cash.get("period_net_cash")) < 0),
    }

    return {
        "scope": {"start": start, "end": end},
        "profit_verdict": verdict,
        "profit_confidence": confidence,
        "conclusion": conclusion,
        "sales_amount": round(sales_amt, 2),
        "sales_cost": None if quality["profit_blocked"] else round(raw_sales_cost, 2),
        "gross_profit": gross_profit,
        "gross_margin": gross_margin,
        "operating_expense": round(expense, 2),
        "operating_profit": operating_profit,
        "operating_margin": operating_margin,
        "purchase_amount": round(purchase_amt, 2),
        "inventory_amount": round(inv_amt, 2),
        "receivables": round(receivables, 2),
        "payables": round(payables, 2),
        "cash": cash,
        "cash_signal": cash_signal,
        "raw_profit_metrics_quarantined": {
            "sales_cost": round(raw_sales_cost, 2),
            "gross_profit": round(raw_gross, 2),
            "gross_margin": round(raw_gross / sales_amt, 4) if sales_amt else None,
            "operating_profit": round(raw_profit, 2),
            "operating_margin": round(raw_profit / sales_amt, 4) if sales_amt else None,
            "reason": "仅保留作审计线索；质量门阻断时不得作为经营结论。",
        },
        "reference_cost_scenario": reference,
        "cost_quality": cost,
        "data_quality": {
            **quality,
            "sales_rows": len(sales), "purchase_rows": len(purchases), "expense_rows": len(expenses),
            "inventory_rows": len(inv), "receivable_rows": len(ar), "payable_rows": len(ap),
        },
        "expense_completeness": {
            "confirmed": expenses_complete,
            "note": "默认只确认系统费用记录，不自动假设房租、工资、税费等已完整录入。",
        },
        "profit_definition": "经营口径；成本异常时利润被阻断。即使成本正常，费用完整性未确认时也不等于审计净利润。",
    }


def purchases(start: str, end: str, top_n: int = 20) -> dict[str, Any]:
    rows = flow("purchase", start, end)
    by_vendor: dict[str, float] = {}
    for r in rows:
        by_vendor[r["vendor"]] = by_vendor.get(r["vendor"], 0.0) + float(r.get("purchase_amount") or 0)
    top = sorted(({"vendor": k, "amount": round(v, 2)} for k, v in by_vendor.items()), key=lambda x: x["amount"], reverse=True)[:max(1, min(top_n, 100))]
    return {"scope": {"start": start, "end": end}, "purchase_amount": round(sum(float(x.get("purchase_amount") or 0) for x in rows), 2), "rows": len(rows), "top_vendors": top, "pagination_integrity": "merged_by_order_id"}


def inventory_view(top_n: int = 20) -> dict[str, Any]:
    rows = inventory()
    top = sorted(rows, key=lambda x: x["inventory_amount"], reverse=True)[:max(1, min(top_n, 100))]
    return {"inventory_amount": round(sum(float(x.get("inventory_amount") or 0) for x in rows), 2), "rows": len(rows),
            "negative_count": sum(1 for x in rows if float(x.get("qty") or 0) < 0),
            "zero_cost_positive_qty": sum(1 for x in rows if float(x.get("qty") or 0) > 0 and float(x.get("avg_cost") or 0) <= 0), "top": top}


def products(start: str, end: str, top_n: int = 20) -> dict[str, Any]:
    rows = flow("sales", start, end)
    acc: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = str(r.get("product_id") or r.get("product") or "")
        x = acc.setdefault(key, {"product": r.get("product") or "", "product_id": r.get("product_id"), "sales": 0.0, "cost": 0.0, "qty": 0.0, "anomaly_rows": 0})
        x["sales"] += float(r.get("sales_amount") or 0)
        x["cost"] += float(r.get("sales_cost") or 0)
        x["qty"] += float(r.get("qty") or 0)
        x["anomaly_rows"] += int(_is_cost_suspicious(r))
    out = []
    for x in acc.values():
        anomaly = x["anomaly_rows"] > 0
        gross = x["sales"] - x["cost"]
        out.append({"product": x["product"], "product_id": x["product_id"], "sales": round(x["sales"], 2), "qty": round(x["qty"], 2),
                    "cost": None if anomaly else round(x["cost"], 2), "gross": None if anomaly else round(gross, 2),
                    "gross_margin": None if anomaly or not x["sales"] else round(gross / x["sales"], 4),
                    "cost_status": "anomalous" if anomaly else "usable", "anomaly_rows": x["anomaly_rows"]})
    out.sort(key=lambda x: x["sales"], reverse=True)
    return {"scope": {"start": start, "end": end}, "products": out[:max(1, min(top_n, 100))],
            "note": "成本异常商品不输出毛利，避免把异常成本转成错误利润排行。"}


def quality(start: str, end: str) -> dict[str, Any]:
    sales = flow("sales", start, end)
    purchases_rows = flow("purchase", start, end)
    inv = inventory()
    exp = base._expenses(start, end)
    cost = reconcile_cost(sales, purchases_rows, inv)
    report = quality_report(sales, inv, exp, cost)
    return {"scope": {"start": start, "end": end}, "quality": report, "cost_quality": cost,
            "ok_for_profit": not report["profit_blocked"]}
