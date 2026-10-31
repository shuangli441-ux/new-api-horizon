from __future__ import annotations

import hmac
import json
import math
import os
import random
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

BASE_URL = os.getenv("MZ_BASE_URL", "https://mz.bizgo.com/CXF/rs").rstrip("/")
CLIENT_VER = os.getenv("MZ_CLIENT_VER", "5.7.9.6")
CN_TZ = timezone(timedelta(hours=8))

app = FastAPI(title="Miaozhang Read Tool Service", version="1.0.0")


def _f(v: Any, default: float = 0.0) -> float:
    if v in (None, "", "-"):
        return float(default)
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("¥", "").replace("￥", "").strip()
    try:
        return float(s)
    except Exception:
        import re
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else float(default)


def _auth(authorization: str | None) -> None:
    expected = str(os.getenv("MZ_TOOL_TOKEN", "") or "")
    if not expected:
        raise HTTPException(status_code=503, detail="tool token not configured")
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="unauthorized")


def _scope(start: str | None, end: str | None) -> tuple[str, str]:
    today = datetime.now(CN_TZ).date()
    s = date.fromisoformat(start) if start else today.replace(day=1)
    e = date.fromisoformat(end) if end else today
    if s > e:
        raise HTTPException(status_code=400, detail="start must not be after end")
    return s.isoformat(), e.isoformat()


class ToolRequest(BaseModel):
    start: str | None = None
    end: str | None = None
    top_n: int = 20


class MiaozhangSession:
    def __init__(self):
        self.s = requests.Session()
        self.lock = threading.RLock()
        self.owner: dict[str, Any] | None = None
        self.login_at = 0.0

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "x-mz-ver": CLIENT_VER,
            "x-mz-time": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "x-mz-traceid": uuid.uuid4().hex[:9],
            "Origin": "https://mz.bizgo.com",
            "Referer": "https://mz.bizgo.com/index.html",
        }

    def _call(self, method: str, path: str, body: Any = None, retries: int = 2) -> Any:
        q = {"t": str(random.random()), "r": str(random.random())}
        if method == "GET":
            q["_"] = str(int(time.time() * 1000))
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                resp = self.s.request(method, BASE_URL + path, params=q, json=body,
                                      headers=self._headers(), timeout=35)
                if resp.status_code != 200:
                    raise RuntimeError(f"upstream_http_{resp.status_code}")
                data = resp.json()
                if not isinstance(data, dict) or data.get("errorCode") != 0:
                    raise RuntimeError("upstream_business_error")
                return data.get("data")
            except Exception as exc:
                last = exc
                if attempt < retries:
                    time.sleep(0.8 * (2 ** attempt))
        raise RuntimeError(str(last or "upstream_failed"))

    def login(self) -> dict[str, Any]:
        username = str(os.getenv("MZ_USERNAME", "") or "").strip()
        password = str(os.getenv("MZ_PASSWORD", "") or "")
        if not username or not password:
            raise HTTPException(status_code=503, detail="miaozhang credentials not configured")
        body = {"username": username, "password": password, "random": str(int(time.time() * 1000))}
        data = self._call("POST", "/direct/sys/user/token/create", body, retries=0) or {}
        owner = self._call("GET", "/crm/owner/get", retries=1) or {}
        owner_vo = owner.get("ownerVO") or {}
        owner_id = owner.get("ownerId") or owner_vo.get("id")
        branch_id = owner.get("branchId") or owner_vo.get("branchId")
        name = (owner_vo.get("enterpriseInfoVO") or {}).get("name")
        if not owner_id or not branch_id or not name:
            raise RuntimeError("owner_verification_failed")
        login_owner = data.get("ownerId") or (data.get("ownerVO") or {}).get("id")
        if login_owner and int(login_owner) != int(owner_id):
            raise RuntimeError("owner_identity_mismatch")
        expected = str(os.getenv("MZ_EXPECTED_OWNER_ID", "") or "").strip()
        if expected and int(expected) != int(owner_id):
            raise RuntimeError("unexpected_owner")
        self.owner = {"owner_id": owner_id, "branch_id": branch_id, "owner_name": name}
        self.login_at = time.monotonic()
        return dict(self.owner)

    def ensure(self) -> dict[str, Any]:
        with self.lock:
            if self.owner is None or time.monotonic() - self.login_at > 1200:
                return self.login()
            return dict(self.owner)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        with self.lock:
            self.ensure()
            try:
                return self._call("POST", path, body)
            except RuntimeError as exc:
                if "business" in str(exc):
                    self.owner = None
                raise


MZ = MiaozhangSession()


def _grid(names: list[str]) -> list[dict[str, Any]]:
    return [{"name": n, "show": True, "sort": i} for i, n in enumerate(names)]


def _flow_body(kind: str, start: str, end: str, page: int, page_size: int = 100) -> dict[str, Any]:
    sales = kind == "sales"
    body: dict[str, Any] = {
        "transverseModel": "normal",
        "orderUnpaidAmtNotZeroFlag": False,
        "pageNum": page,
        "pageSize": page_size,
        "beginDate": start,
        "endDate": end,
        "clientType": "customer" if sales else "vendor",
        "dateType": "orderDate",
        "platform": "PC",
        "showYardsFlag": False,
        "isGift": False,
        "sortList": [{"sortColumn": "date", "sortOrder": "desc"}],
        "filingFlag": False,
        "uniSign": str(uuid.uuid4()),
    }
    if sales:
        body.update({"showNegativeProfitFlag": False, "showZeroAvgPriceFlag": False})
        body["pagePropertyJson"] = {
            "configJson": {"transverseModel": "normal"},
            "mergeSameProd": False,
            "recalculateQtyAndAmt": False,
            "source": "pc",
            "salesFlowGrid": _grid(["date", "clientName", "productName", "displayQty", "rawTotalAmt", "purchasePrice", "rawGrossProfitAmt", "branchName", "salesman", "createdBy"]),
        }
    else:
        body["pagePropertyJson"] = {
            "configJson": {"transverseModel": "normal"},
            "mergeSameProd": False,
            "recalculateQtyAndAmt": False,
            "source": "pc",
            "purchaseFlowGrid": _grid(["date", "clientName", "productName", "displayQty", "purchasePrice", "rawTotalAmt", "branchName", "salesman", "createdBy"]),
        }
    return body


def _flow(kind: str, start: str, end: str, max_pages: int = 80) -> list[dict[str, Any]]:
    path = "/report/flow/sales/pageDetailList" if kind == "sales" else "/report/flow/purchase/pageDetailList"
    rows: list[dict[str, Any]] = []
    seen_pages: set[str] = set()
    for page in range(max_pages):
        data = MZ.post(path, _flow_body(kind, start, end, page)) or {}
        page_orders: list[dict[str, Any]] = []
        for day in data.get("dateVOs") or []:
            page_orders.extend(day.get("orderVOs") or [])
        if not page_orders:
            break
        sig = json.dumps(page_orders, sort_keys=True, ensure_ascii=False)
        if sig in seen_pages:
            raise RuntimeError("flow_page_repeated")
        seen_pages.add(sig)
        for order in page_orders:
            summary = order.get("sum") or {}
            for d in order.get("detailVOs") or []:
                amt = _f(d.get("rawTotalAmt") or d.get("fullRawTotalAmt"))
                if kind == "sales":
                    gp_raw = d.get("rawGrossProfitAmt")
                    gross = _f(gp_raw, default=float("nan"))
                    if math.isnan(gross):
                        gross = amt - _f(d.get("qty")) * _f(d.get("purchasePrice"))
                    rows.append({
                        "date": order.get("date") or d.get("delyDate"),
                        "client": order.get("clientName") or "",
                        "product": d.get("productName") or "",
                        "qty": _f(d.get("qty")),
                        "sales_amount": amt,
                        "sales_cost": amt - gross,
                        "gross_profit": gross,
                        "unit_cost": _f(d.get("purchasePrice")),
                        "order_id": order.get("orderId"),
                        "order_no": order.get("orderNumber"),
                        "unpaid": _f(summary.get("orderUnpaidAmt")),
                    })
                else:
                    rows.append({
                        "date": order.get("date") or d.get("delyDate"),
                        "vendor": order.get("clientName") or "",
                        "product": d.get("productName") or "",
                        "qty": _f(d.get("qty")),
                        "purchase_amount": amt,
                        "unit_price": _f(d.get("purchasePrice")),
                        "order_id": order.get("orderId"),
                        "order_no": order.get("orderNumber"),
                        "unpaid": _f(summary.get("orderUnpaidAmt")),
                    })
    return rows


def _inventory(page_size: int = 200, max_pages: int = 80) -> list[dict[str, Any]]:
    base = {
        "queryType": "inventory", "prodAvailable": True, "pageNum": 0, "pageSize": page_size,
        "showPositiveQty": True, "showNegativeAndZeroQty": True, "shoesHatsModuleFlag": False,
        "showQtyType": "qty", "sortList": [{"sortColumn": "createDate", "sortOrder": "desc"}],
        "filingFlag": False, "prodWHIds": [],
    }
    total_raw = MZ.post("/prod/inventory/getTotal", dict(base))
    total = int(total_raw or 0)
    out: list[dict[str, Any]] = []
    for page in range(max_pages):
        body = dict(base); body["pageNum"] = page
        data = MZ.post("/prod/inventory/pageList", body) or {}
        items = (data.get("inventoryPageVo") or {}).get("list") or []
        if not items:
            break
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
                avg = _f(x.get("avgCost")); break
        if avg is None:
            avg = _f(r.get("showAvgCost"))
        qty = _f(r.get("qty"))
        rows.append({
            "product": r.get("prodName") or "", "qty": qty, "avg_cost": avg,
            "inventory_amount": qty * avg, "warehouse": r.get("prodWHName") or "",
            "product_id": r.get("prodId"), "inventory_id": r.get("id"),
            "available_qty": _f(r.get("availableQty")), "warn_min": _f(r.get("warnMinQty")),
            "warn_max": _f(r.get("warnMaxQty")),
        })
    return rows


def _receivables(end: str, max_pages: int = 80) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for page in range(max_pages):
        body = {
            "pageNum": page, "pageSize": 200, "beginDate": "2010-01-01", "endDate": end,
            "clientType": "customer", "unpaidAmtNotZeroFlag": False, "filingFlag": False,
            "clientFilingFlag": False, "transverseModel": "normal",
            "pagePropertyJson": {"mergeSameProd": False, "recalculateQtyAndAmt": False, "source": "pc",
                "salesArrearsGrid": _grid(["clientName", "contractAmt", "paidAmt", "unPaidAmt", "advanceAmt"])},
        }
        data = MZ.post("/report/account/salesArrears/pageList", body) or {}
        items = data.get("detailVOs") or []
        if not items: break
        for r in items:
            key = r.get("clientId") or r.get("clientName")
            if key in seen: continue
            seen.add(key)
            rows.append({"client": r.get("clientName") or "", "amount": _f(r.get("unPaidAmt")),
                         "contract_amount": _f(r.get("contractAmt")), "paid": _f(r.get("paidAmt")),
                         "advance": _f(r.get("advanceAmt")), "client_id": r.get("clientId")})
        total_rows = int(data.get("totalRows") or 0)
        if total_rows and len(seen) >= total_rows: break
        if len(items) < 200 and not total_rows: break
    return rows


def _payables(end: str, max_pages: int = 80) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(max_pages):
        body = {"available": True, "clientClassifyId": [], "beginCreateDate": "2010-01-01 00:00:00",
                "endCreateDate": end + " 23:59:59", "filingFlag": False, "clientFilingFlag": False,
                "id": None, "clientType": "vendor", "clientSalesIds": [], "sortList": [],
                "pageNum": page, "pageSize": 200}
        data = MZ.post("/crm/client/vendor/pageList", body) or {}
        items = data.get("list") or []
        if not items: break
        for r in items:
            unpaid = _f(r.get("unpaidAmt"))
            if unpaid:
                rows.append({"vendor": r.get("name") or "", "amount": unpaid, "vendor_id": r.get("id"),
                             "contract_amount": _f(r.get("contractAmt")), "paid": _f(r.get("paidAmt")),
                             "advance": _f(r.get("advanceAmt"))})
        total = int(data.get("total") or 0)
        if total and (page + 1) * 200 >= total: break
        if len(items) < 200 and not total: break
    return rows


def _expenses(start: str, end: str, max_pages: int = 80) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(max_pages):
        body = {"beginCreateDate": start + " 00:00:00", "endCreateDate": end + " 23:59:59",
                "cashFlowTypes": [], "hasShare": [], "filingFlag": False, "sortList": [],
                "pageNum": page, "pageSize": 200}
        data = MZ.post("/sys/cashFlow/pageList", body) or {}
        items = data.get("list") or []
        if not items: break
        for r in items:
            typ = str(r.get("cashFlowType") or "")
            if typ.lower().startswith("expense"):
                rows.append({"date": r.get("orderDate") or r.get("createDate"),
                             "category": r.get("detailName") or r.get("categoryName") or "未分类",
                             "amount": abs(_f(r.get("amt"))), "branch": r.get("branchName") or "",
                             "remark": r.get("remark") or "", "order_no": r.get("orderNumber")})
        total = int(data.get("total") or 0)
        if total and (page + 1) * 200 >= total: break
        if len(items) < 200 and not total: break
    return rows


def _cash(start: str, end: str) -> dict[str, Any]:
    accounts_data = MZ.post("/sys/payWay/balance/pageList", {"account": "", "branchIds": None, "measureAmtFlag": True}) or {}
    accounts = []
    for r in accounts_data.get("list") or []:
        accounts.append({"name": r.get("account") or "", "balance": None if r.get("accountBalance") in (None, "", "-") else _f(r.get("accountBalance")),
                         "available": r.get("available"), "id": r.get("id")})
    body = {"beginDate": start, "endDate": end, "capitalTypes": ["income", "expense", "Interturn"],
            "balance": 0, "pageSize": 100, "pageNum": 0,
            "sortList": [{"sortColumn": "date", "sortOrder": "desc"}],
            "netProfitsNonProdExpenseFlag": False, "filingFlag": False, "transverseModel": "normal",
            "pagePropertyJson": {"mergeSameProd": False, "recalculateQtyAndAmt": False, "source": "pc",
                                 "capitalFlowGrid": _grid(["branchName", "date", "payWay", "clientName", "income", "expense", "balance"])}}
    total_data = MZ.post("/report/account/capitalFlow/total", body) or {}
    total = total_data.get("total") or {}
    return {"accounts": accounts, "account_balance": sum(x["balance"] or 0 for x in accounts),
            "period_income": _f(total.get("income")), "period_expense": _f(total.get("expense")),
            "period_net_cash": _f(total.get("income")) - _f(total.get("expense")),
            "period_opening": _f(total_data.get("periodBalance")), "period_closing": _f(total.get("balance"))}


def _overview(start: str, end: str) -> dict[str, Any]:
    sales = _flow("sales", start, end)
    purchases = _flow("purchase", start, end)
    expenses = _expenses(start, end)
    inv = _inventory()
    ar = _receivables(end)
    ap = _payables(end)
    cash = _cash(start, end)
    sales_amt = sum(x["sales_amount"] for x in sales)
    sales_cost = sum(x["sales_cost"] for x in sales)
    gross = sales_amt - sales_cost
    expense = sum(x["amount"] for x in expenses)
    profit = gross - expense
    return {
        "scope": {"start": start, "end": end},
        "sales_amount": round(sales_amt, 2), "sales_cost": round(sales_cost, 2),
        "gross_profit": round(gross, 2), "gross_margin": round(gross / sales_amt, 4) if sales_amt else None,
        "operating_expense": round(expense, 2), "operating_profit": round(profit, 2),
        "operating_margin": round(profit / sales_amt, 4) if sales_amt else None,
        "purchase_amount": round(sum(x["purchase_amount"] for x in purchases), 2),
        "inventory_amount": round(sum(x["inventory_amount"] for x in inv), 2),
        "receivables": round(sum(x["amount"] for x in ar), 2),
        "payables": round(sum(x["amount"] for x in ap), 2),
        "cash": cash,
        "data_quality": {"sales_rows": len(sales), "purchase_rows": len(purchases), "expense_rows": len(expenses),
                         "inventory_rows": len(inv), "receivable_rows": len(ar), "payable_rows": len(ap)},
        "profit_definition": "经营口径：销售额-销售成本-系统费用记录；不是审计净利润",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "miaozhang-tool-service", "version": "1.0.0",
            "credentials_configured": bool(os.getenv("MZ_USERNAME") and os.getenv("MZ_PASSWORD")),
            "expected_owner_configured": bool(os.getenv("MZ_EXPECTED_OWNER_ID")), "read_only": True,
            "tools": ["overview", "purchases", "inventory", "receivables", "payables", "cash", "products", "quality"]}


@app.post("/tools/overview")
def overview(req: ToolRequest, authorization: str | None = Header(default=None)):
    _auth(authorization); start, end = _scope(req.start, req.end)
    return _overview(start, end)


@app.post("/tools/purchases")
def purchases(req: ToolRequest, authorization: str | None = Header(default=None)):
    _auth(authorization); start, end = _scope(req.start, req.end)
    rows = _flow("purchase", start, end)
    by_vendor: dict[str, float] = {}
    for r in rows: by_vendor[r["vendor"]] = by_vendor.get(r["vendor"], 0.0) + r["purchase_amount"]
    top = sorted(({"vendor": k, "amount": round(v, 2)} for k, v in by_vendor.items()), key=lambda x: x["amount"], reverse=True)[:max(1, min(req.top_n, 100))]
    return {"scope": {"start": start, "end": end}, "purchase_amount": round(sum(x["purchase_amount"] for x in rows), 2), "rows": len(rows), "top_vendors": top}


@app.post("/tools/inventory")
def inventory(req: ToolRequest, authorization: str | None = Header(default=None)):
    _auth(authorization); rows = _inventory(); top_n = max(1, min(req.top_n, 100))
    top = sorted(rows, key=lambda x: x["inventory_amount"], reverse=True)[:top_n]
    return {"inventory_amount": round(sum(x["inventory_amount"] for x in rows), 2), "rows": len(rows),
            "negative_count": sum(1 for x in rows if x["qty"] < 0), "zero_cost_positive_qty": sum(1 for x in rows if x["qty"] > 0 and x["avg_cost"] <= 0), "top": top}


@app.post("/tools/receivables")
def receivables(req: ToolRequest, authorization: str | None = Header(default=None)):
    _auth(authorization); _, end = _scope(req.start, req.end); rows = _receivables(end)
    rows.sort(key=lambda x: x["amount"], reverse=True)
    return {"as_of": end, "amount": round(sum(x["amount"] for x in rows), 2), "rows": len(rows), "top": rows[:max(1, min(req.top_n, 100))]}


@app.post("/tools/payables")
def payables(req: ToolRequest, authorization: str | None = Header(default=None)):
    _auth(authorization); _, end = _scope(req.start, req.end); rows = _payables(end)
    rows.sort(key=lambda x: x["amount"], reverse=True)
    return {"as_of": end, "amount": round(sum(x["amount"] for x in rows), 2), "rows": len(rows), "top": rows[:max(1, min(req.top_n, 100))]}


@app.post("/tools/cash")
def cash(req: ToolRequest, authorization: str | None = Header(default=None)):
    _auth(authorization); start, end = _scope(req.start, req.end); return _cash(start, end)


@app.post("/tools/products")
def products(req: ToolRequest, authorization: str | None = Header(default=None)):
    _auth(authorization); start, end = _scope(req.start, req.end); rows = _flow("sales", start, end)
    acc: dict[str, dict[str, float]] = {}
    for r in rows:
        x = acc.setdefault(r["product"], {"sales": 0.0, "cost": 0.0, "gross": 0.0, "qty": 0.0})
        x["sales"] += r["sales_amount"]; x["cost"] += r["sales_cost"]; x["gross"] += r["gross_profit"]; x["qty"] += r["qty"]
    out = [{"product": k, **{a: round(b, 2) for a, b in v.items()}, "gross_margin": round(v["gross"] / v["sales"], 4) if v["sales"] else None} for k, v in acc.items()]
    out.sort(key=lambda x: x["sales"], reverse=True)
    return {"scope": {"start": start, "end": end}, "products": out[:max(1, min(req.top_n, 100))], "loss_products": [x for x in out if x["gross"] < 0][:max(1, min(req.top_n, 100))]}


@app.post("/tools/quality")
def quality(req: ToolRequest, authorization: str | None = Header(default=None)):
    _auth(authorization); start, end = _scope(req.start, req.end)
    sales = _flow("sales", start, end); inv = _inventory(); exp = _expenses(start, end)
    issues = {
        "sales_zero_or_negative_cost": sum(1 for x in sales if x["sales_amount"] > 0 and x["sales_cost"] <= 0),
        "loss_sales_rows": sum(1 for x in sales if x["sales_amount"] < x["sales_cost"]),
        "negative_inventory": sum(1 for x in inv if x["qty"] < 0),
        "positive_inventory_zero_cost": sum(1 for x in inv if x["qty"] > 0 and x["avg_cost"] <= 0),
        "unclassified_expense": sum(1 for x in exp if x["category"] == "未分类"),
    }
    return {"scope": {"start": start, "end": end}, "issues": issues, "ok_for_profit": issues["sales_zero_or_negative_cost"] == 0}
