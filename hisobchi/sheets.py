"""Google Sheets bilan sinxronlash (Google Apps Script web-app orqali, Google Cloud kerak emas)."""
import logging
import os

import httpx

log = logging.getLogger(__name__)

TYPE_LABEL = {"in": "Kirim", "out": "Chiqim"}
SOURCE_LABEL = {"text": "matn", "photo": "skrinshot", "voice": "ovoz"}


def enabled() -> bool:
    return bool(os.environ.get("SHEETS_WEBHOOK_URL"))


def _row(r: dict) -> dict:
    amount = float(r["amount"])
    return {
        "id": r["id"],
        "date": r["tx_date"].isoformat(),
        "type": TYPE_LABEL.get(r["direction"], r["direction"]),
        "amount": amount if r["direction"] == "in" else -amount,
        "currency": r["currency"],
        "category": r["category"],
        "person": r.get("person") or "",
        "note": r.get("note") or "",
        "source": SOURCE_LABEL.get(r.get("source"), r.get("source") or ""),
    }


async def _post(payload: dict) -> bool:
    url = os.environ.get("SHEETS_WEBHOOK_URL")
    if not url:
        return True
    payload["secret"] = os.environ.get("SHEETS_SECRET", "")
    try:
        # Apps Script javobni 302 bilan boshqa manzilga yo'naltiradi
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
            r = await http.post(url, json=payload)
        data = r.json() if r.status_code == 200 else {}
        if not data.get("ok"):
            log.error("Sheets error %s: %s", r.status_code, r.text[:300])
            return False
        return True
    except (httpx.HTTPError, ValueError):
        log.exception("Sheets request failed")
        return False


async def add(rows: list[dict]) -> bool:
    return await _post({"action": "add", "rows": [_row(r) for r in rows]})


async def delete(ids: list[int]) -> bool:
    return await _post({"action": "delete", "ids": ids})


async def replace_all(rows: list[dict]) -> bool:
    return await _post({"action": "replace_all", "rows": [_row(r) for r in rows]})
