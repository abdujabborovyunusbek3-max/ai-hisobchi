"""Claude orqali matn/rasmni tahlil qilish va Groq Whisper orqali ovozni matnga aylantirish."""
import base64
import json
import logging
import os
from datetime import date

import anthropic
import httpx

log = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
GROQ_MODEL = os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3")

client = anthropic.AsyncAnthropic()

SYSTEM_PROMPT = """You are the bookkeeping engine of a personal Telegram accounting bot. The owner is an Uzbek speaker; messages may be in Uzbek (Latin or Cyrillic), Russian, English, or a mix, and may be voice transcripts with recognition errors.

Classify each message:
- "record": it reports one or more money movements. Extract every movement into `transactions`.
- "query": it asks about totals, balances, history or debts. Fill `query` with filters; the bot computes the numbers itself, so never compute totals yourself.
- "other": greetings, thanks, or messages with no financial content. Put a short, friendly answer in `reply`.

Rules for transactions:
- direction "out" = money left the owner (berdim, to'ladim, sotib oldim, xarajat, ketdi, o'tkazdim, qarz berdim).
- direction "in" = money came to the owner (oldim, tushdi, keldi, sotdim, qarzini qaytardi, oylik oldim, qarz oldim).
- category: one short lowercase Uzbek word or phrase, e.g. oylik, qarz, qarz qaytarish, ijara, oziq-ovqat, transport, kommunal, aloqa, savdo, sovg'a, sog'liq, ta'lim, boshqa. Reuse an existing category from the list below when one fits.
- amount: a plain positive number in units of the currency. "100 000", "100ming", "100k" -> 100000; "1.5 mln", "bir yarim million" -> 1500000; "50$" -> 50 with currency USD.
- currency: ISO code. Default UZS (so'm) unless another currency is stated.
- person: the counterparty's name in its base form without Uzbek case suffixes (Aliga -> Ali, Validan -> Vali, Akmalni -> Akmal, Karimovga -> Karimov), capitalized. Reuse an existing name from the list below when it is clearly the same person. null if no person is named.
- note: a few words of useful context (what it was for, merchant, card). Empty string if nothing to add.
- date: YYYY-MM-DD if the message or screenshot shows a date ("kecha" = yesterday, "o'tgan dushanba" etc.), otherwise null.

Screenshots: payment receipts and transfer screens (Click, Payme, Uzum, Paynet, bank apps, cheklar). An outgoing transfer or purchase is "out"; an incoming transfer is "in". The bot owner's name is given below: if the owner (or a shortened form like "Ali V." for "Ali Valiyev") is the sender, the money left the owner, so direction is "out" and person is the recipient; if the owner is the recipient, direction is "in" and person is the sender. Never use the owner as person. Use the service or merchant as note. Ignore commission lines unless the commission is the only amount. A statement with several operations gives several transactions. A failed/cancelled payment is not a transaction. If an image has no financial content, use intent "other" and say so.

Rules for query: fill only the filters the question needs; leave the others null. Relative periods are resolved against today's date ("bu oy" = first day of this month to today, "o'tgan oy", "bu hafta", "bugun", "kecha"). direction is "all" unless the question is clearly only about income or only about expenses.

Always fill `reply` with one short sentence in Uzbek (Latin script) that the bot can show the user, e.g. what was understood or why nothing was recorded."""

_NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["record", "query", "other"]},
        "transactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "currency": {"type": "string"},
                    "direction": {"type": "string", "enum": ["in", "out"]},
                    "category": {"type": "string"},
                    "person": _NULLABLE_STR,
                    "note": {"type": "string"},
                    "date": _NULLABLE_STR,
                },
                "required": ["amount", "currency", "direction", "category", "person", "note", "date"],
                "additionalProperties": False,
            },
        },
        "query": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "person": _NULLABLE_STR,
                        "category": _NULLABLE_STR,
                        "direction": {"type": "string", "enum": ["in", "out", "all"]},
                        "date_from": _NULLABLE_STR,
                        "date_to": _NULLABLE_STR,
                    },
                    "required": ["person", "category", "direction", "date_from", "date_to"],
                    "additionalProperties": False,
                },
            ]
        },
        "reply": {"type": "string"},
    },
    "required": ["intent", "transactions", "query", "reply"],
    "additionalProperties": False,
}


class AIError(Exception):
    """Foydalanuvchiga ko'rsatiladigan xato."""


async def analyze(*, today: date, text: str | None = None, image: bytes | None = None,
                  image_mime: str = "image/jpeg", categories: list[str] = (), people: list[str] = (),
                  owner_name: str = "") -> dict:
    """Xabarni (matn va/yoki rasm) tahlil qiladi va OUTPUT_SCHEMA bo'yicha dict qaytaradi."""
    context = (f"Today's date: {today.isoformat()} ({today.strftime('%A')}).\n"
               f"Bot owner (\"me\"): {owner_name or 'unknown'}\n"
               f"Existing categories: {', '.join(categories) or '(none yet)'}\n"
               f"Known people: {', '.join(people) or '(none yet)'}")
    content: list[dict] = []
    if image is not None:
        content.append({"type": "image", "source": {"type": "base64", "media_type": image_mime,
                                                    "data": base64.standard_b64encode(image).decode()}})
    content.append({"type": "text", "text": f"{context}\n\nMessage:\n{text or '(screenshot, no caption)'}"})

    try:
        response = await _create(content)
    except anthropic.AuthenticationError as e:
        raise AIError("ANTHROPIC_API_KEY noto'g'ri yoki o'rnatilmagan.") from e
    except anthropic.RateLimitError as e:
        raise AIError("Claude hozir band (limit). Birozdan keyin qayta yuboring.") from e
    except anthropic.APIStatusError as e:
        log.exception("Claude API error")
        if "credit balance" in str(e.message).lower() or e.status_code == 402:
            raise AIError("API hisobida mablag' tugagan. Balansni to'ldiring.") from e
        raise AIError(f"Claude xatosi ({e.status_code}): {str(e.message)[:300]}") from e
    except anthropic.APIConnectionError as e:
        raise AIError("Claude bilan aloqa yo'q. Keyinroq urinib ko'ring.") from e

    if response.stop_reason == "refusal":
        raise AIError("Bu xabarni tahlil qilib bo'lmadi.")
    text_out = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text_out:
        raise AIError("Claude javob bermadi.")
    try:
        return _extract_json(text_out)
    except ValueError as e:
        log.error("JSON emas: %s", text_out[:500])
        raise AIError("Javobni tushunib bo'lmadi. Qayta yuboring.") from e


def _extract_json(text: str) -> dict:
    """Javobdan JSON obyektni ajratib oladi (```json ... ``` ichida bo'lsa ham)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no json")
    return json.loads(text[start:end + 1])


# Rasmiy API (api.anthropic.com) bo'lmasa, vositachi xizmat structured output yoki beta
# parametrlarini qo'llamasligi mumkin. Shunda oddiy "faqat JSON qaytar" usuliga o'tamiz.
_OFFICIAL_API = "anthropic.com" in (os.environ.get("ANTHROPIC_BASE_URL") or "api.anthropic.com")
_plain_mode = not _OFFICIAL_API

_PLAIN_INSTRUCTION = ("\n\nRespond with ONLY one JSON object (no markdown, no extra text) that matches this "
                      "JSON Schema:\n" + json.dumps(OUTPUT_SCHEMA))


async def _create(content: list[dict]):
    global _plain_mode
    if not _plain_mode:
        try:
            return await client.beta.messages.create(
                model=MODEL, max_tokens=8000, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
        except anthropic.BadRequestError:
            log.warning("Structured output ishlamadi, oddiy JSON rejimiga o'tildi", exc_info=True)
            _plain_mode = True
    return await client.messages.create(
        model=MODEL, max_tokens=8000, system=SYSTEM_PROMPT + _PLAIN_INSTRUCTION,
        messages=[{"role": "user", "content": content}],
    )


async def transcribe(audio: bytes, filename: str = "voice.ogg") -> str:
    """Ovozli xabarni Groq Whisper orqali matnga aylantiradi."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise AIError("Ovozli xabarlar uchun GROQ_API_KEY o'rnatilmagan.")
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (filename, audio, "audio/ogg" if filename.endswith(".ogg") else "application/octet-stream")},
            data={"model": GROQ_MODEL, "language": "uz", "response_format": "json", "temperature": "0",
                  "prompt": "Pul hisobi: so'm, ming, million, oylik, qarz, ijara, berdim, oldim, to'ladim."},
        )
    if r.status_code != 200:
        log.error("Groq error %s: %s", r.status_code, r.text[:500])
        if r.status_code == 401:
            raise AIError("GROQ_API_KEY noto'g'ri. Render'da kalitni tekshiring.")
        try:
            detail = r.json().get("error", {}).get("message", "")[:200]
        except ValueError:
            detail = r.text[:200]
        raise AIError(f"Ovozni matnga aylantirib bo'lmadi (Groq {r.status_code}: {detail}).")
    return r.json().get("text", "").strip()
