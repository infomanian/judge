import os
import base64
import math
from typing import List
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from anthropic import Anthropic

APP_TITLE = "دادگاه شبیه‌سازی‌شده (قاضی هوشمند)"
APP_DESC = "وب‌اپ برای شبیه‌سازی دادرسی بین شاکی، متشاکی و قاضی (Claude)"
APP_VERSION = "0.2.0"

# تنظیمات chunking
CHUNK_SIZE = 4000  # تقریباً کاراکتر؛ می‌تونید کمتر/بیشتر کنید
CHUNK_SUMMARY_MAX_TOKENS = 600
FINAL_MAX_TOKENS = 2500

app = FastAPI(title=APP_TITLE, description=APP_DESC, version=APP_VERSION)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "replace-me-with-secure-key"))

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-1-20250805") 
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


def split_text_into_chunks(text: str, max_chars: int = CHUNK_SIZE) -> List[str]:
    """
    تقسیم متن به بخش‌هایی با طول حداکثر max_chars.
    تلاش می‌کنیم برش‌ها را روی نقطه یا خط جدید انجام دهیم تا جمله‌ها نصفه نماند.
    """
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    L = len(text)
    while start < L:
        end = min(start + max_chars, L)
        if end < L:
            # سعی کن نزدیک به end روی نقطه/پرانتز/خط جدید برش بزنی
            sep_positions = []
            for sep in (".", "؟", "!", "\n", "؛"):
                pos = text.rfind(sep, start, end)
                if pos != -1:
                    sep_positions.append(pos + 1)
            if sep_positions:
                end = max(sep_positions)
        chunks.append(text[start:end].strip())
        start = end
    return chunks


def build_judge_system_prompt() -> str:
    return (
        "شما نقش یک قاضی بی‌طرف در دادگاه شبیه‌سازی‌شده را دارید. "
        "هدف شما هدایت رسیدگی، پرسیدن سوالات لازم از طرفین در صورت نیاز و در نهایت صدور رأی مستدل است. "
        "در مراحل خلاصه‌سازی بخش‌ها فقط نکات کلیدی (طرفین، تاریخ‌ها، ادعاها، مدارک مهم، خواسته) را استخراج کنید. "
        "در مرحلهٔ نهایی، بر اساس خلاصهٔ جمع‌شده و مدارک تصویری/متن‌های پیوست‌شده رأی نهایی شامل: "
        "خلاصه دعوی، تحلیل حقوقی، استناد به مواد/قواعد (در صورت امکان) و نتیجه را صادر کن."
    )


def make_user_blocks_from_text(text: str):
    """ساخت یک بلاک content از نوع متن برای ارسال به API"""
    return [{"type": "text", "text": text}]


def make_image_block_from_bytes(file_bytes: bytes, mime: str, name: str):
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": mime,
            "data": base64.b64encode(file_bytes).decode("utf-8"),
            "name": name
        }
    }


def call_anthropic_with_blocks(system_prompt: str, content_blocks: List[dict], max_tokens: int):
    """
    فراخوانی همگانی Anthropic. 
    - system_prompt جداگانه ارسال می‌شود.
    - content_blocks لیستی از بلاک‌ها (هر بلاک dict با type = text|image) است.
    """
    if not client:
        raise RuntimeError("Anthropic client not configured (ANTHROPIC_API_KEY missing).")

    if not content_blocks:
        # API حداقل یک پیام user می‌خواهد.
        content_blocks = [{"type": "text", "text": "(هیچ محتوایی ارسال نشده)"}]

    # messages: هر entry یک پیام user با content = لیست بلاک‌ها
    messages = [{"role": "user", "content": content_blocks}]
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        system=system_prompt,
        messages=messages,
        max_tokens=max_tokens
    )
    # جمع‌آوری متن پاسخ
    return resp.content[0].text if hasattr(resp, "content") else str(resp)


async def process_uploaded_files_for_chunks(attachments: List[UploadFile]):
    """
    فایل‌های آپلودی را پردازش می‌کند:
    - برای فایل متنی، متن را برمی‌گرداند (برای chunking).
    - برای تصویر، بایت‌ها را برمی‌گرداند تا فقط در نهایی ارسال شوند.
    """
    text_parts = []
    image_blocks = []
    if not attachments:
        return text_parts, image_blocks

    for up in attachments:
        if not up.filename:
            continue
        file_bytes = await up.read()
        mime = up.content_type or "application/octet-stream"
        if mime.startswith("image/"):
            image_blocks.append(make_image_block_from_bytes(file_bytes, mime, up.filename))
        else:
            # تلاش برای دیکد متن
            try:
                txt = file_bytes.decode("utf-8", errors="ignore").strip()
                if txt:
                    text_parts.append(f"[فایل متنی: {up.filename}]\n{txt}")
                else:
                    text_parts.append(f"[فایل متنی: {up.filename}] (خالی یا غیرقابل خواندن)")
            except Exception:
                text_parts.append(f"[فایل: {up.filename}] (قابل خواندن به عنوان متن نیست)")
    return text_parts, image_blocks


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/court")


@app.get("/court", response_class=HTMLResponse)
async def court_index(request: Request):
    if "history" not in request.session:
        request.session["history"] = []
    return templates.TemplateResponse("court.html", {"request": request, "title": APP_TITLE, "history": request.session["history"]})


@app.post("/court_step", response_class=HTMLResponse)
async def court_step(request: Request,
                     role: str = Form(...),  # plaintiff / defendant
                     message: str = Form(""),
                     attachments: List[UploadFile] | None = File(None)):
    """
    جریان:
    1) پیام طرف (متن و فایل‌ها) را می‌گیریم.
    2) متن‌ها را جمع می‌کنیم؛ اگر طولانی بود chunk می‌کنیم و هر chunk را خلاصه می‌کنیم.
    3) خلاصه‌ها را جمع‌آوری و یک درخواست نهایی برای تولید لایحه می‌زنیم.
    4) پاسخ قاضی را به تاریخچه اضافه می‌کنیم.
    """
    if not ANTHROPIC_API_KEY or client is None:
        raise HTTPException(status_code=500, detail="کلید Anthropic تنظیم نشده است.")

    # دریافت تاریخچه
    history = request.session.get("history", [])

    # پردازش فایل‌ها (آسیب‌پذیر بودن: ممکنه attachments None باشه)
    attachments = attachments or []
    uploaded_texts, uploaded_image_blocks = await process_uploaded_files_for_chunks(attachments)

    # assemble full textual input: combine message + uploaded textual files + previous important fields (if any)
    # برای ساده‌سازی، ما از message فقط استفاده می‌کنیم؛ در نسخهٔ کامل میتوان فیلدهای فرم را هم اضافه کرد.
    full_text = message or ""
    if uploaded_texts:
        full_text = full_text + "\n\n" + "\n\n".join(uploaded_texts)

    # احتمالا بخواهی تاریخچهٔ قبلی را هم در نظر بگیری؛ می‌توانیم تمام پیام‌های قبلی user را به عنوان context اضافه کنیم:
    # در این پیاده‌سازی، تاریخچه شامل dictهایی است که در append می‌کنیم (role, message, files)
    for h in history:
        if h.get("message"):
            full_text = full_text + "\n\n" + (h.get("role", "") + ": " + h.get("message"))

    # append current user entry into history (نام فایل‌ها فقط برای نمایش)
    entry = {"role": role, "message": message, "files": [up.filename for up in attachments if up.filename]}
    history.append(entry)

    # اگر متن خالی و هیچ فایل تصویری هم نبود => صرفا پیام ثبت و قاضی واکنش عمومی می‌دهد
    # اما برای فرستادن به مدل حداقل یک بلاک متن لازم است.
    system_prompt = build_judge_system_prompt()

    # تصمیم‌گیری: آیا نیاز به chunking است؟
    if len(full_text) > CHUNK_SIZE:
        # تقسیم و خلاصه‌سازی هر تکه
        chunks = split_text_into_chunks(full_text, CHUNK_SIZE)
        summaries = []
        for i, chunk in enumerate(chunks, start=1):
            # پرامپت خلاصه‌سازی
            chunk_system = (
                "شما نقش یک خلاصه‌ساز حقوقی دارید. این بخش از متن را خلاصه کنید و فقط روی "
                "نکات کلیدی تمرکز کنید: طرفین، تاریخ/زمان‌ها، ادعاها، مستندات اشاره‌شده و خواسته‌ها. "
                "خلاصه را به زبان فارسی و کوتاه (حداکثر 300-400 کلمه) تحویل دهید."
            )
            # ارسال chunk به مدل (فقط متن chunk را می‌فرستیم)
            content_blocks = make_user_blocks_from_text(f"بخش {i} از {len(chunks)}:\n\n{chunk}")
            try:
                summary_text = call_anthropic_with_blocks(chunk_system, content_blocks, CHUNK_SUMMARY_MAX_TOKENS)
            except Exception as e:
                # در صورت خطا خلاصه ساده از خود chunk برگردان
                summary_text = f"[خلاصه‌ساز دچار خطا شد برای بخش {i}: {e}]\n" + (chunk[:1000] + "...")
            summaries.append(summary_text.strip())

        # ترکیب خلاصه‌ها
        combined_summary = "\n\n".join([f"خلاصه بخش {idx+1}:\n{txt}" for idx, txt in enumerate(summaries)])
        # حالا مرحلهٔ نهایی: ارسال combined_summary + تصاویر (در صورت وجود) + system prompt قاضی
        final_blocks = [ {"type": "text", "text": "خلاصهٔ ترکیبی بخش‌ها:\n\n" + combined_summary} ]

        # تصاویر فقط یک‌بار در نهایی می‌فرستیم
        final_blocks.extend(uploaded_image_blocks)

        # صدا زدن مدل برای تولید پاسخ قاضی (لایحه / سوال یا رأی)
        try:
            judge_text = call_anthropic_with_blocks(system_prompt, final_blocks, FINAL_MAX_TOKENS)
        except Exception as e:
            judge_text = f"❌ خطا در تولید پاسخ نهایی: {e}"

    else:
        # متن کوتاه است -> مستقیم یک درخواست نهایی با متن کامل و تصاویر می‌فرستیم
        final_blocks = [ {"type": "text", "text": full_text} ]
        final_blocks.extend(uploaded_image_blocks)
        try:
            judge_text = call_anthropic_with_blocks(system_prompt, final_blocks, FINAL_MAX_TOKENS)
        except Exception as e:
            judge_text = f"❌ خطا در تولید پاسخ نهایی: {e}"

    # append judge response to history
    history.append({"role": "judge", "message": judge_text, "files": []})
    request.session["history"] = history

    return templates.TemplateResponse("court.html", {"request": request, "title": APP_TITLE, "history": history})
