from __future__ import annotations

import os
import sys

import requests


def main() -> int:
    key = str(os.getenv("MZ_MODEL_API_KEY", "") or "")
    url = str(os.getenv("MZ_MODEL_API_URL", "https://api.deepseek.com/chat/completions") or "")
    model = str(os.getenv("MZ_MODEL_NAME", "deepseek-flash") or "")
    if not key or not url or not model:
        print("MODEL_PROBE=CONFIG_MISSING")
        return 2
    try:
        resp = requests.post(
            url,
            json={
                "model": model,
                "messages": [{"role": "user", "content": "只回答 OK"}],
                "thinking": {"type": "disabled"},
                "temperature": 0,
                "max_tokens": 16,
            },
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code >= 400:
            print(f"MODEL_PROBE=HTTP_{resp.status_code}")
            return 3
        data = resp.json()
        text = str((((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or "").strip()
        if not text:
            print("MODEL_PROBE=EMPTY")
            return 4
        print("MODEL_PROBE=PASS")
        return 0
    except Exception:
        print("MODEL_PROBE=REQUEST_FAILED")
        return 5


if __name__ == "__main__":
    sys.exit(main())
