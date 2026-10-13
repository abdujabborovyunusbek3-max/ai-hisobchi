"""Hisobotlarni hisoblash va chiroyli matn qilib chiqarish (hamma hisob-kitob kodda, AI emas)."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from html import escape

CURRENCY_LABEL = {"UZS": "so'm", "USD": "$", "RUB": "rubl", "EUR": "€"}


def money(amount: Decimal, currency: str) -> str:
    amount = Decimal(amount)
    s = f"{amount:,.2f}".rstrip("0").rstrip(".").replace(",", " ")
    return f"{s} {CURRENCY_LABEL.get(currency, currency)}"


def period_range(name: str, today: date) -> tuple[date | None, date | None, str]:
    name = (name or "oy").lower()
    if name in ("bugun", "kun"):
        return today, today, "Bugun"
    if name == "kecha":
        d = today - timedelta(days=1)
        return d, d, "Kecha"
    if name == "hafta":
        start = today - timedelta(days=today.weekday())
        return start, today, "Shu hafta"
    if name == "yil":
        return today.replace(month=1, day=1), today, f"{today.year}-yil"
    if name in ("hammasi", "barchasi", "all"):
        return None, None, "Barcha vaqt"
    return today.replace(day=1), today, "Shu oy"


def tx_line(r: dict) -> str:
    sign = "➕" if r["direction"] == "in" else "➖"
    parts = [f"{sign} <b>{money(r['amount'], r['currency'])}</b>", escape(r["category"])]
    if r.get("person"):
        parts.append(escape(r["person"]))
    line = " · ".join(parts)
    if r.get("note"):
        line += f" <i>({escape(r['note'])})</i>"
    return line


def build_report(rows: list[dict], title: str) -> str:
    if not rows:
        return f"📊 <b>{escape(title)}</b>\n\nHech qanday yozuv topilmadi."

    totals = defaultdict(lambda: {"in": Decimal(0), "out": Decimal(0)})
    by_cat = defaultdict(lambda: defaultdict(lambda: {"in": Decimal(0), "out": Decimal(0)}))
    by_person = defaultdict(lambda: defaultdict(lambda: {"in": Decimal(0), "out": Decimal(0)}))
    for r in rows:
        cur, d, amt = r["currency"], r["direction"], Decimal(r["amount"])
        totals[cur][d] += amt
        by_cat[cur][r["category"]][d] += amt
        if r.get("person"):
            by_person[cur][r["person"]][d] += amt

    out = [f"📊 <b>{escape(title)}</b>  ({len(rows)} ta yozuv)"]
    for cur in sorted(totals):
        t = totals[cur]
        out.append("")
        if len(totals) > 1:
            out.append(f"<b>[{cur}]</b>")
        out.append(f"➕ Kirim: <b>{money(t['in'], cur)}</b>")
        out.append(f"➖ Chiqim: <b>{money(t['out'], cur)}</b>")
        out.append(f"🟰 Qoldiq: <b>{money(t['in'] - t['out'], cur)}</b>")

        out.append("\n<u>Kategoriyalar bo'yicha:</u>")
        for cat, v in sorted(by_cat[cur].items(), key=lambda kv: -(kv[1]["in"] + kv[1]["out"])):
            bits = []
            if v["in"]:
                bits.append(f"+{money(v['in'], cur)}")
            if v["out"]:
                bits.append(f"−{money(v['out'], cur)}")
            out.append(f"• {escape(cat)}: {' / '.join(bits)}")

        if by_person[cur]:
            out.append("\n<u>Odamlar bo'yicha:</u>")
            for person, v in sorted(by_person[cur].items(), key=lambda kv: -(kv[1]["in"] + kv[1]["out"]))[:15]:
                bits = []
                if v["out"]:
                    bits.append(f"berildi {money(v['out'], cur)}")
                if v["in"]:
                    bits.append(f"olindi {money(v['in'], cur)}")
                out.append(f"• {escape(person)}: {', '.join(bits)}")
    return "\n".join(out)
