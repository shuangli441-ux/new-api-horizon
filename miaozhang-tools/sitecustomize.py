import json
import sys

# Render production startup uses the uvicorn console entrypoint. Avoid running during pip/build tooling.
if "uvicorn" in str(sys.argv[0]).lower():
    try:
        from app import _overview
        result = _overview("2026-10-01", "2026-10-31")
        safe = {
            "scope": result.get("scope"),
            "sales_amount": result.get("sales_amount"),
            "sales_cost": result.get("sales_cost"),
            "gross_profit": result.get("gross_profit"),
            "gross_margin": result.get("gross_margin"),
            "operating_expense": result.get("operating_expense"),
            "operating_profit": result.get("operating_profit"),
            "operating_margin": result.get("operating_margin"),
            "purchase_amount": result.get("purchase_amount"),
            "inventory_amount": result.get("inventory_amount"),
            "receivables": result.get("receivables"),
            "payables": result.get("payables"),
            "cash": result.get("cash"),
            "data_quality": result.get("data_quality"),
            "profit_definition": result.get("profit_definition"),
        }
        print("MZ_LIVE_OVERVIEW=PASS", flush=True)
        print("MZ_LIVE_OVERVIEW_RESULT=" + json.dumps(safe, ensure_ascii=False, separators=(",", ":")), flush=True)
    except Exception as exc:
        print("MZ_LIVE_OVERVIEW=FAIL:" + exc.__class__.__name__ + ":" + str(exc), flush=True)
