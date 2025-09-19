import os
import base64
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from anthropic import Anthropic

APP_TITLE = "دادگاه شبیه‌سازی‌شده (قاضی هوشمند)"
APP_DESC = "وب‌اپ برای شبیه‌سازی دادرسی بین شاکی، متشاکی و قاضی (Claude)"
APP_VERSION = "0.1.0"

app = FastAPI(title=APP_TITLE, description=APP_DESC, version=APP_VERSION)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "replace-me-with-secure-key"))

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-1-20250805") 
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


@app.get("/court", response_class=HTMLResponse)
async def court_index(request: Request):
    if "history" not in request.session:
        request.session["history"] = []
    return templates.TemplateResponse("court.html", {"request": request, "title": APP_TITLE, "history": request.session["history"]})


@app.post("/court_step", response_class=HTMLResponse)
async def court_step(request: Request,
                     role: str = Form(...),  # plaintiff / defendant
                     message: str = Form(""),
                     attachments: list[UploadFile] | None = File(None)):
    if not ANTHROPIC_API_KEY or client is None:
        raise HTTPException(status_code=500, detail="کلید Anthropic تنظیم نشده است.")

    history = request.session.get("history", [])

    # اضافه کردن پیام طرفین (شاکی یا متشاکی)
    entry = {"role": role, "message": message, "files": []}

    # پردازش فایل‌ها
    content_blocks = []
    if attachments:
        for up in attachments:
            if up.filename:
                file_bytes = await up.read()
                mime = up.content_type or "application/octet-stream"

                if mime.startswith("image/"):
                    content_blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": base64.b64encode(file_bytes).decode("utf-8")
                        }
                    })
                    entry["files"].append(f"(تصویر: {up.filename})")
                else:
                    text_data = file_bytes.decode("utf-8", errors="ignore")
                    content_blocks.append({"type": "text", "text": text_data})
                    entry["files"].append(f"(متن: {up.filename})")

    # متن پیام طرف شاکی یا متشاکی
    if message.strip():
        content_blocks.append({"type": "text", "text": message.strip()})

    history.append(entry)

    # ساخت prompt قاضی
    judge_prompt = """شما نقش یک قاضی در یک دادگاه شبیه‌سازی‌شده را دارید.
۱. لوایح و مستندات هر دو طرف (شاکی و متشاکی) را بررسی کن.
۲. اگر نیاز به توضیح یا مدرک بیشتر داری، سوال بپرس.
۳. وقتی اطلاعات کافی شد، یک رأی نهایی صادر کن.
۴. رأی شامل خلاصه دعوی، تحلیل حقوقی و نتیجه باشد.
"""

    # ترکیب تاریخچه به مدل
    all_messages = [{"role": "system", "content": [{"type": "text", "text": judge_prompt}]}]
    for h in history:
        role_map = "user"
        prefix = "شاکی" if h["role"] == "plaintiff" else "متشاکی"
        txt = f"{prefix}: {h['message']}" if h["message"] else prefix
        blocks = [{"type": "text", "text": txt}] + [{"type": "text", "text": f} for f in h["files"]]
        all_messages.append({"role": role_map, "content": blocks})

    # پاسخ قاضی
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1000,
        messages=all_messages
    )
    judge_text = resp.content[0].text if hasattr(resp, "content") else str(resp)

    history.append({"role": "judge", "message": judge_text, "files": []})
    request.session["history"] = history

    return templates.TemplateResponse("court.html", {"request": request, "title": APP_TITLE, "history": history})


@app.get("/healthz")
async def health():
    return {"status": "ok"}
