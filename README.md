# AI hisobchi — Telegram bot

Shaxsiy hisob-kitob boti. Matn, chek/skrinshot yoki ovozli xabar yuborasiz — bot summani, kimga/kimdan, nima uchun (oylik, qarz, ijara...) ekanini o'zi ajratib yozib boradi va so'rasangiz hisobot beradi.

| Nima yuborasiz | Bot nima qiladi |
|---|---|
| `100 000 oylik berdim Aliga` | ➖ 100 000 so'm · oylik · Ali |
| Click / Payme / bank skrinshoti | Summa, kimga, sana — rasmdan o'qiydi |
| 🎤 ovozli xabar | Matnga aylantiradi va yozadi |
| `bu oy qancha oylik berdim?` | Hisobotni kodda aniq hisoblab beradi |

Buyruqlar: `/hisobot [bugun|hafta|oy|yil|hammasi]`, `/oxirgi`, `/ochir [raqam]`, `/export` (CSV/Excel), `/sheets` (Google Sheets'ni yangilash), `/yordam`.
Har bir yozuv ostida **❌ Bekor qilish** tugmasi bor.

## Qanday ishlaydi
- **Claude API** — matn va rasmlarni tushunadi (model `CLAUDE_MODEL` bilan o'zgartiriladi).
- **Groq Whisper** — ovozli xabarni matnga aylantiradi (bepul).
- **Postgres (Neon, bepul)** — yozuvlar saqlanadi. `DATABASE_URL` bo'lmasa lokal SQLite.
- Hamma summa va qoldiqlar AI emas, kod tomonidan hisoblanadi.
- Faqat egasi foydalana oladi: `OWNER_IDS` yoki birinchi `/start` bosgan odam.

## Kerakli kalitlar (environment variables)
| O'zgaruvchi | Qayerdan |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → API Keys (balansga kamida $5) |
| `ANTHROPIC_BASE_URL` | Faqat vositachi xizmat (MWAPI kabi) bo'lsa: `https://api.mwapi.dev`. Rasmiy kalitda bo'sh |
| `CLAUDE_MODEL` | Model nomi, masalan `claude-opus-5-5` (vositachida "Model Plaza"dagi nomni yozing) |
| `GROQ_API_KEY` | https://console.groq.com → API Keys (bepul) |
| `DATABASE_URL` | https://neon.tech → yangi loyiha → Connection string |
| `OWNER_IDS` | Sizning Telegram ID (@userinfobot dan bilib olasiz) |

Token va kalitlarni **hech qachon** kodga yozmang — faqat hosting sozlamalariga.

## Google Sheets'ga ulash (ixtiyoriy, bepul)
Har bir yozuv "Hisob" varag'iga qator bo'lib tushadi, "Jami" varag'ida kirim/chiqim va oylar bo'yicha jadval chiqadi.
1. https://sheets.new da yangi jadval oching.
2. **Kengaytmalar (Extensions) → Apps Script**. Ochilgan oynadagi kodni o'chirib, `sheets/apps_script.gs` ichidagini joylang.
3. Kodning tepasidagi `SECRET` qiymatini o'zingiz o'ylab topgan maxfiy so'zga almashtiring va saqlang (💾).
4. **Deploy → New deployment** → turi: **Web app**. *Execute as*: **Me**, *Who has access*: **Anyone** → **Deploy**. Google ruxsat so'raydi: **Authorize access** → hisobingiz → **Advanced → Go to ... (unsafe)** → **Allow**.
5. Chiqqan **Web app URL** (`https://script.google.com/macros/s/.../exec`) ni nusxalang.
6. Render → ai-hisobchi → **Environment**: `SHEETS_WEBHOOK_URL` = shu URL, `SHEETS_SECRET` = 3-qadamdagi so'z → **Save, rebuild and deploy**.
7. Botga `/sheets` yozing: avvalgi barcha yozuvlar jadvalga ko'chiriladi.

## Render.com ga joylash (bepul)
1. https://render.com ga GitHub orqali kiring.
2. **New → Blueprint** → shu repozitoriyani tanlang (`render.yaml` avtomatik o'qiladi).
3. So'ralgan kalitlarni kiriting → **Apply**.
4. Deploy tugagach botga `/start` yozing.

Bepul tarifda servis 15 daqiqa ishlatilmasa "uxlaydi"; keyingi xabarga javob ~1 daqiqa kechikadi (Telegram xabarni qayta yuboradi, yo'qolmaydi). Pullik tarifga ($7/oy) o'tsangiz bu yo'qoladi.

## Lokal ishga tushirish
```bash
pip install -r requirements.txt
cp .env.example .env   # qiymatlarni to'ldiring
set -a; . ./.env; set +a
python -m hisobchi.main   # WEBHOOK_URL bo'lmasa polling rejimida ishlaydi
python tests/test_bot.py  # testlar
```
