"""Lokal testlar: Claude va Telegram chaqiruvlari soxtalashtirilgan."""
import asyncio
import json
import os
import sys
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ["OWNER_IDS"] = "42"
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import httpx2 as httpx  # noqa: E402  (anthropic SDK httpx2 ishlatadi)

from hisobchi import ai, db, main, report  # noqa: E402

db.engine.dispose()
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
db.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
db.init_db()


def make_update(text=None):
    msg = MagicMock()
    msg.text = text
    msg.reply_text = AsyncMock()
    msg.chat.send_action = AsyncMock()
    upd = MagicMock()
    upd.effective_message = msg
    upd.message = msg
    upd.effective_user.id = 42
    return upd


def test_record_and_query():
    ai_results = [
        {"intent": "record", "reply": "", "query": None, "transactions": [
            {"amount": 100000, "currency": "UZS", "direction": "out", "category": "oylik", "person": "Ali",
             "note": "", "date": None},
            {"amount": 500000, "currency": "UZS", "direction": "in", "category": "qarz", "person": "Vali",
             "note": "", "date": "2026-10-01"}]},
        {"intent": "query", "reply": "", "transactions": [], "query": {
            "person": "Ali", "category": None, "direction": "all", "date_from": None, "date_to": None}},
    ]
    main.analyze = AsyncMock(side_effect=ai_results)
    upd = make_update("100 000 oylik berdim Aliga, Validan 500 ming qarz oldim")
    asyncio.run(main.process(upd, text=upd.message.text))
    out = upd.message.reply_text.call_args.args[0]
    assert "100 000 so'm" in out and "Ali" in out and "01.10.2026" in out, out

    upd2 = make_update("Aliga qancha berdim?")
    asyncio.run(main.process(upd2, text=upd2.message.text))
    out2 = upd2.message.reply_text.call_args.args[0]
    assert "-100 000" in out2 and "Vali" not in out2, out2
    print(out2)


def test_report_totals():
    rows = db.query_transactions(42)
    text = report.build_report(rows, "Hammasi")
    assert "+500 000" in text and "400 000" in text and "<pre>" in text, text
    assert report.money(Decimal("1500000.50"), "USD") == "1 500 000.5 $"


def test_delete():
    last = db.last_transaction_id(42)
    assert db.delete_transactions(42, [last]) == 1
    assert db.delete_transactions(7, [1]) == 0  # boshqa odamning yozuvi o'chmaydi


def test_claude_request_shape():
    """SDK so'rovni to'g'ri yig'ishini tekshiradi (tarmoqsiz)."""
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content)
        seen["beta"] = request.headers.get("anthropic-beta")
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "text", "text": json.dumps(
                {"intent": "other", "transactions": [], "query": None, "reply": "Salom!"})}]})

    import anthropic
    ai.client = anthropic.AsyncAnthropic(api_key="x", base_url="http://test",
                                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    res = asyncio.run(ai.analyze(today=date(2026, 10, 13), text="salom", image=b"\xff\xd8",
                                 categories=["oylik"], people=["Ali"]))
    assert res["reply"] == "Salom!"
    body = seen["body"]
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in seen["beta"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["messages"][0]["content"][0]["type"] == "image"


def test_plain_mode_for_proxy():
    """Vositachi xizmat (MWAPI kabi): beta parametrlarsiz, JSON matndan ajratiladi."""
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "msg_2", "type": "message", "role": "assistant", "model": "m",
            "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "text", "text": '```json\n{"intent": "other", "transactions": [], '
                                                 '"query": null, "reply": "Ok"}\n```'}]})

    import anthropic
    ai.client = anthropic.AsyncAnthropic(api_key="x", base_url="http://proxy",
                                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    ai._plain_mode = True
    res = asyncio.run(ai.analyze(today=date(2026, 10, 13), text="salom"))
    assert res["reply"] == "Ok"
    assert "fallbacks" not in seen["body"] and "output_config" not in seen["body"]
    assert "JSON Schema" in seen["body"]["system"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
