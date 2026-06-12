"""
TG Doc Agent — бесплатный ИИ-агент для генерации документов в Telegram.
Форматы: PDF, DOCX, XLSX, CSV, TXT, PPTX.
ИИ: Google Gemini (бесплатный tier).
"""

import io
import json
import logging
import os

import asyncio as _asyncio
try:
    _asyncio.get_event_loop()
except RuntimeError:
    _asyncio.set_event_loop(_asyncio.new_event_loop())

import requests
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("doc-agent")
# не светим токен в логах: глушим HTTP-логи библиотек
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

BOT_TOKEN = os.environ["BOT_TOKEN"]
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
PORT = int(os.environ.get("PORT", "10000"))

TEMPLATES_FILE = "templates.json"
FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf")
FONT_BOLD_PATH = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans-Bold.ttf")


def load_templates() -> dict:
    if os.path.exists(TEMPLATES_FILE):
        with open(TEMPLATES_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_template(user_id: int, text: str):
    data = load_templates()
    data[str(user_id)] = text[:8000]
    with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def get_template(user_id: int) -> str:
    return load_templates().get(str(user_id), "")


def call_groq(prompt: str, system: str) -> str:
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_KEY}"},
        json={
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        },
        timeout=120,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Groq вернул {r.status_code}")
    return r.json()["choices"][0]["message"]["content"]


def call_gemini(prompt: str, system: str) -> str:
    import time
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    models = [GEMINI_MODEL, "gemini-2.0-flash-lite", "gemini-2.5-flash-lite"]
    last_err = None
    for model in models:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        headers = {"x-goog-api-key": GEMINI_KEY}
        for attempt in range(2):
            r = requests.post(url, json=body, headers=headers, timeout=120)
            if r.status_code == 429:
                last_err = "Лимит запросов Gemini (429)"
                time.sleep(5)
                continue
            if r.status_code != 200:
                last_err = f"Gemini вернул {r.status_code}"
                break
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    raise RuntimeError(last_err or "Gemini недоступен")


def llm(prompt: str, system: str = "") -> str:
    """Пробуем провайдеров по очереди: Groq → Gemini."""
    errors = []
    if GROQ_KEY:
        try:
            return call_groq(prompt, system)
        except Exception as e:
            errors.append(str(e))
            log.warning("Groq failed: %s", e)
    if GEMINI_KEY:
        try:
            return call_gemini(prompt, system)
        except Exception as e:
            errors.append(str(e))
            log.warning("Gemini failed: %s", e)
    raise RuntimeError("; ".join(errors) or "Нет настроенных ИИ-провайдеров")


PLAN_SYSTEM = """Ты — генератор документов. Пользователь пишет запрос на русском.
Твоя задача — вернуть ТОЛЬКО валидный JSON без markdown-обёрток:
{
 "format": "pdf" | "docx" | "xlsx" | "csv" | "txt" | "pptx",
 "filename": "короткое_имя_без_расширения",
 "title": "Заголовок документа",
 "content": ...
}

Правила выбора format:
- юзер сказал формат явно → используй его
- презентация/слайды → pptx
- таблица/данные/учёт → xlsx (или csv если просили csv)
- гайд/чек-лист/инструкция/документ → pdf
- если просили ворд/docx → docx
- заметка/простой текст → txt

Структура content по формату:
- pdf/docx/txt: [{"type":"heading","text":"..."} | {"type":"paragraph","text":"..."} | {"type":"bullets","items":["...","..."]} | {"type":"checklist","items":["...","..."]}]
- xlsx/csv: {"headers":["..."],"rows":[["..."],["..."]]}
- pptx: [{"title":"Заголовок слайда","bullets":["...","..."]}]

Контент делай содержательным, полным и полезным.
Если дан ОБРАЗЕЦ — точно копируй его структуру, стиль, тон и оформление."""


def plan_document(user_request: str, template: str) -> dict:
    prompt = user_request
    if template:
        prompt += f"\n\n--- ОБРАЗЕЦ ПОЛЬЗОВАТЕЛЯ ---\n{template}"
    raw = llm(prompt, PLAN_SYSTEM)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        raw = raw[4:] if raw.startswith("json") else raw
    return json.loads(raw.strip())


def make_pdf(plan: dict) -> bytes:
    from fpdf import FPDF
    pdf = FPDF(format="A4")
    pdf.add_font("DejaVu", "", FONT_PATH)
    pdf.add_font("DejaVu", "B", FONT_BOLD_PATH)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_font("DejaVu", "B", 18)
    pdf.multi_cell(0, 10, plan["title"], new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    for block in plan["content"]:
        t = block["type"]
        if t == "heading":
            pdf.set_font("DejaVu", "B", 14)
            pdf.ln(3)
            pdf.multi_cell(0, 8, block["text"], new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        elif t == "paragraph":
            pdf.set_font("DejaVu", "", 11)
            pdf.multi_cell(0, 6, block["text"], new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif t == "bullets":
            pdf.set_font("DejaVu", "", 11)
            for item in block["items"]:
                pdf.multi_cell(0, 6, f"  •  {item}", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif t == "checklist":
            pdf.set_font("DejaVu", "", 11)
            for item in block["items"]:
                pdf.multi_cell(0, 7, f"  [ ]  {item}", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
    return bytes(pdf.output())


def make_docx(plan: dict) -> bytes:
    from docx import Document
    from docx.shared import Pt
    doc = Document()
    doc.add_heading(plan["title"], level=0)
    for block in plan["content"]:
        t = block["type"]
        if t == "heading":
            doc.add_heading(block["text"], level=1)
        elif t == "paragraph":
            doc.add_paragraph(block["text"])
        elif t == "bullets":
            for item in block["items"]:
                doc.add_paragraph(item, style="List Bullet")
        elif t == "checklist":
            for item in block["items"]:
                p = doc.add_paragraph()
                p.add_run(f"[ ]  {item}").font.size = Pt(11)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_xlsx(plan: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = plan["title"][:30]
    c = plan["content"]
    ws.append(c["headers"])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4472C4")
    for row in c["rows"]:
        ws.append(row)
    for col in ws.columns:
        width = max(len(str(cell.value or "")) for cell in col) + 3
        ws.column_dimensions[col[0].column_letter].width = min(width, 50)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_csv(plan: dict) -> bytes:
    import csv
    c = plan["content"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(c["headers"])
    w.writerows(c["rows"])
    return buf.getvalue().encode("utf-8-sig")


def make_txt(plan: dict) -> bytes:
    lines = [plan["title"], "=" * len(plan["title"]), ""]
    for block in plan["content"]:
        t = block["type"]
        if t == "heading":
            lines += ["", block["text"].upper(), "-" * len(block["text"])]
        elif t == "paragraph":
            lines += [block["text"], ""]
        elif t in ("bullets", "checklist"):
            mark = "[ ]" if t == "checklist" else "•"
            lines += [f"  {mark} {i}" for i in block["items"]] + [""]
    return "\n".join(lines).encode("utf-8")


def make_pptx(plan: dict) -> bytes:
    from pptx import Presentation
    from pptx.util import Pt
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = plan["title"]
    for s in plan["content"]:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = s["title"]
        body = slide.placeholders[1].text_frame
        body.clear()
        for i, b in enumerate(s["bullets"]):
            p = body.paragraphs[0] if i == 0 else body.add_paragraph()
            p.text = b
            p.font.size = Pt(20)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


GENERATORS = {
    "pdf": make_pdf, "docx": make_docx, "xlsx": make_xlsx,
    "csv": make_csv, "txt": make_txt, "pptx": make_pptx,
}

START_TEXT = (
    "Привет! Я генерирую документы по твоему запросу 📄\n\n"
    "Просто напиши, что нужно, например:\n"
    "• «чек-лист запуска телеграм-канала в PDF»\n"
    "• «презентация про нейросети, 5 слайдов»\n"
    "• «таблица учёта расходов в excel»\n"
    "• «гайд по prompt-инжинирингу в ворде»\n\n"
    "📎 Пришли мне свой файл-образец (.txt, .docx, .pdf) — "
    "и я буду генерить документы в твоём стиле.\n\n"
    "Команды:\n"
    "/template — показать текущий образец\n"
    "/clear — удалить образец"
)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_TEXT)


async def cmd_template(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = get_template(update.effective_user.id)
    if t:
        await update.message.reply_text(f"Текущий образец (первые 500 символов):\n\n{t[:500]}")
    else:
        await update.message.reply_text("Образец не загружен. Пришли мне файл — я запомню его стиль.")


async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_templates()
    data.pop(str(update.effective_user.id), None)
    with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    await update.message.reply_text("Образец удалён ✅")


def extract_text_from_file(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith((".txt", ".md", ".csv")):
        return data.decode("utf-8", errors="ignore")
    if name.endswith(".docx"):
        from docx import Document
        doc = Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs)
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return ""
    return ""


async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if doc.file_size > 5 * 1024 * 1024:
        await update.message.reply_text("Файл слишком большой (макс 5 МБ).")
        return
    f = await doc.get_file()
    data = bytes(await f.download_as_bytearray())
    text = extract_text_from_file(doc.file_name or "", data)
    if not text.strip():
        await update.message.reply_text("Не смог прочитать файл 😕 Поддерживаю: .txt, .md, .docx, .pdf, .csv")
        return
    save_template(update.effective_user.id, text)
    await update.message.reply_text("Образец сохранён ✅ Теперь буду генерить документы в этом стиле.\nНапиши, что создать!")


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    await msg.chat.send_action("upload_document")
    status = await msg.reply_text("⏳ Генерирую документ...")
    try:
        template = get_template(update.effective_user.id)
        plan = plan_document(msg.text, template)
        fmt = plan.get("format", "pdf")
        if fmt not in GENERATORS:
            fmt = "pdf"
        file_bytes = GENERATORS[fmt](plan)
        filename = f"{plan.get('filename', 'document')}.{fmt}"
        await msg.reply_document(
            document=io.BytesIO(file_bytes),
            filename=filename,
            caption=f"✅ {plan.get('title', 'Готово')}",
        )
        await status.delete()
    except Exception as e:
        log.exception("generation failed")
        err = str(e)
        if "key=" in err:  # на всякий случай вырезаем ключ из любых ошибок
            err = err.split("key=")[0] + "key=***"
        await status.edit_text(f"Ошибка генерации 😞 Попробуй ещё раз через минуту.\n({err[:200]})")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("template", cmd_template))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if WEBHOOK_URL:
        log.info("Starting in WEBHOOK mode on port %s", PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
        )
    else:
        log.info("Starting in POLLING mode")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
