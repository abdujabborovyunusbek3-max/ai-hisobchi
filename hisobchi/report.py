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


MAX_TABLE_ROWS = 30
NAME_W, CAT_W, SUM_W = 9, 8, 11


def _num(amount: Decimal) -> str:
    return f"{Decimal(amount):,.2f}".rstrip("0").rstrip(".").replace(",", " ")


def _cut(text: str, width: int) -> str:
    text = text or "—"
    return text if len(text) <= width else text[:width - 1] + "…"


def _signed(r: dict) -> str:
    s = ("+" if r["direction"] == "in" else "-") + _num(r["amount"])
    if r["currency"] != "UZS":
        s += r["currency"][:1].lower()  # $ -> "u", rubl -> "r"
    return s


def build_report(rows: list[dict], title: str) -> str:
    """Telegram'da monospace jadval: har bir yozuv bitta qator, pastda jami."""
    if not rows:
        return f"📊 <b>{escape(title)}</b>\n\nHech qanday yozuv topilmadi."

    totals = defaultdict(lambda: {"in": Decimal(0), "out": Decimal(0)})
    for r in rows:
        totals[r["currency"]][r["direction"]] += Decimal(r["amount"])

    shown = rows[-MAX_TABLE_ROWS:]
    width = 5 + 1 + NAME_W + 1 + CAT_W + 1 + SUM_W
    lines = [f"{'Sana':<5} {'Kim':<{NAME_W}} {'Nima':<{CAT_W}} {'Summa':>{SUM_W}}", "─" * width]
    for r in shown:
        lines.append(f"{r['tx_date']:%d.%m} {_cut(r.get('person'), NAME_W):<{NAME_W}} "
                     f"{_cut(r['category'], CAT_W):<{CAT_W}} {_signed(r):>{SUM_W}}")
    lines.append("─" * width)
    for cur in sorted(totals):
        t = totals[cur]
        label = "" if cur == "UZS" else f" ({cur})"
        lines.append(f"{'Kirim' + label:<{width - SUM_W}}{'+' + _num(t['in']):>{SUM_W}}")
        lines.append(f"{'Chiqim' + label:<{width - SUM_W}}{'-' + _num(t['out']):>{SUM_W}}")
        lines.append(f"{'Qoldiq' + label:<{width - SUM_W}}{_num(t['in'] - t['out']):>{SUM_W}}")

    head = f"📊 <b>{escape(title)}</b> · {len(rows)} ta yozuv (so'm)"
    if len(rows) > len(shown):
        head += f"\n<i>Oxirgi {len(shown)} tasi ko'rsatilgan. Hammasi: /export</i>"
    return head + "\n<pre>" + escape("\n".join(lines)) + "</pre>"
