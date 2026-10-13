"""Ma'lumotlar bazasi: Postgres (DATABASE_URL) yoki lokal SQLite."""
import os
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (BigInteger, Column, Date, DateTime, Integer, MetaData, Numeric, String, Table, Text,
                        create_engine, delete, func, insert, or_, select)

metadata = MetaData()

transactions = Table(
    "transactions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False, index=True),
    Column("amount", Numeric(18, 2), nullable=False),
    Column("currency", String(8), nullable=False, default="UZS"),
    Column("direction", String(3), nullable=False),  # "in" | "out"
    Column("category", String(64), nullable=False),
    Column("person", String(128)),
    Column("note", Text),
    Column("source", String(16), nullable=False),  # text | photo | voice
    Column("raw_text", Text),
    Column("tx_date", Date, nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

settings = Table(
    "settings", metadata,
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
)


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///hisobchi.db"
    # Neon/Render "postgres://" yoki "postgresql://" beradi; psycopg3 drayverini tanlaymiz.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


engine = create_engine(_database_url(), pool_pre_ping=True, future=True)


def init_db() -> None:
    metadata.create_all(engine)


def get_setting(key: str) -> str | None:
    with engine.connect() as conn:
        return conn.execute(select(settings.c.value).where(settings.c.key == key)).scalar()


def set_setting(key: str, value: str) -> None:
    with engine.begin() as conn:
        conn.execute(delete(settings).where(settings.c.key == key))
        conn.execute(insert(settings).values(key=key, value=value))


def add_transactions(user_id: int, items: list[dict], source: str, raw_text: str | None) -> list[dict]:
    """items: ai.py qaytargan tranzaksiyalar. Saqlangan qatorlarni (id bilan) qaytaradi."""
    saved = []
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        for it in items:
            row = {
                "user_id": user_id,
                "amount": Decimal(str(it["amount"])).quantize(Decimal("0.01")),
                "currency": (it.get("currency") or "UZS").upper()[:8],
                "direction": it["direction"],
                "category": (it.get("category") or "boshqa").strip().lower()[:64],
                "person": (it.get("person") or None),
                "note": it.get("note") or None,
                "source": source,
                "raw_text": raw_text,
                "tx_date": it["tx_date"],
                "created_at": now,
            }
            row["id"] = conn.execute(insert(transactions).values(**row)).inserted_primary_key[0]
            saved.append(row)
    return saved


def delete_transactions(user_id: int, ids: list[int]) -> int:
    with engine.begin() as conn:
        res = conn.execute(delete(transactions).where(transactions.c.user_id == user_id,
                                                      transactions.c.id.in_(ids)))
        return res.rowcount


def last_transaction_id(user_id: int) -> int | None:
    with engine.connect() as conn:
        return conn.execute(select(transactions.c.id).where(transactions.c.user_id == user_id)
                            .order_by(transactions.c.id.desc()).limit(1)).scalar()


def query_transactions(user_id: int, *, date_from: date | None = None, date_to: date | None = None,
                       person: str | None = None, category: str | None = None,
                       direction: str | None = None, limit: int | None = None,
                       newest_first: bool = False) -> list[dict]:
    t = transactions
    q = select(t).where(t.c.user_id == user_id)
    if date_from:
        q = q.where(t.c.tx_date >= date_from)
    if date_to:
        q = q.where(t.c.tx_date <= date_to)
    if person:
        # "Ali" -> "Ali", "Ali aka" mos keladi, lekin "Vali" emas
        p = person.strip().lower()
        q = q.where(or_(func.lower(t.c.person) == p, func.lower(t.c.person).like(f"{p} %")))
    if category:
        q = q.where(t.c.category.ilike(f"%{category}%"))
    if direction in ("in", "out"):
        q = q.where(t.c.direction == direction)
    order = (t.c.tx_date.desc(), t.c.id.desc()) if newest_first else (t.c.tx_date, t.c.id)
    q = q.order_by(*order)
    if limit:
        q = q.limit(limit)
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(q)]


def known_labels(user_id: int) -> tuple[list[str], list[str]]:
    """Avval ishlatilgan kategoriya va ismlar (AI bir xil nom ishlatishi uchun)."""
    t = transactions
    with engine.connect() as conn:
        cats = conn.execute(select(t.c.category).where(t.c.user_id == user_id).distinct().limit(50)).scalars().all()
        people = conn.execute(select(t.c.person).where(t.c.user_id == user_id, t.c.person.is_not(None))
                              .distinct().limit(100)).scalars().all()
    return sorted(cats), sorted(people)
