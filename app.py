import os
import io
import base64
from typing import List, Tuple
from flask import Flask, render_template, request, session
from anthropic import Anthropic

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    import docx as docx_lib
except Exception:
    docx_lib = None

app = Flask(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-1-20250805") 
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
client = Anthropic(api_key=ANTHROPIC_API_KEY)
app.secret_key = os.getenv("SESSION_SECRET", "amir")
# conversation_history = []

def build_anthropic_content(role: str, text: str, files) -> Tuple[List[dict], List[str]]:
    """Build Claude content blocks from text and uploaded files.
    Returns (content_blocks, file_summaries_for_history).
    """
    blocks: List[dict] = [{"type": "text", "text": f"نقش: {role}\nتوضیحات:\n{text}"}]
    history_summaries: List[str] = []

    for f in files:
        if not f or not f.filename:
            continue
        data = f.read()
        mime = (f.mimetype or "application/octet-stream").lower()
        name = f.filename

        # Images: send as image blocks
        if mime.startswith("image/"):
            try:
                b64 = base64.b64encode(data).decode("ascii")
                blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime, "data": b64},
                })
                history_summaries.append(f"[تصویر: {name} | {mime} | {len(data)//1024}KB]")
                continue
            except Exception:
                history_summaries.append(f"[تصویر نامعتبر: {name}]")
                continue

        # PDFs: extract text (if pypdf available)
        if mime == "application/pdf" and PdfReader is not None:
            try:
                reader = PdfReader(io.BytesIO(data))
                pages_text = []
                for page in reader.pages[:10]:  # limit pages for prompt size
                    try:
                        pages_text.append(page.extract_text() or "")
                    except Exception:
                        pages_text.append("")
                extracted = "\n\n".join(pages_text).strip()
                snippet = extracted[:4000]
                if snippet:
                    blocks.append({"type": "text", "text": f"متن استخراج‌شده از PDF {name}:\n{snippet}"})
                history_summaries.append(f"[PDF: {name} | حداکثر 10 صفحه استخراج شد]")
                continue
            except Exception:
                history_summaries.append(f"[PDF نامعتبر: {name}]")
                # fall through to generic text try

        # DOCX: extract text (if python-docx available)
        if mime in ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",) and docx_lib is not None:
            try:
                doc = docx_lib.Document(io.BytesIO(data))
                paragraphs = [p.text for p in doc.paragraphs]
                extracted = "\n".join(paragraphs)
                snippet = extracted[:4000]
                if snippet:
                    blocks.append({"type": "text", "text": f"متن استخراج‌شده از DOCX {name}:\n{snippet}"})
                history_summaries.append(f"[DOCX: {name} | {len(paragraphs)} پاراگراف]")
                continue
            except Exception:
                history_summaries.append(f"[DOCX نامعتبر: {name}]")
                # fall through to generic text try

        # Text-like files
        if mime.startswith("text/") or mime in ("application/json",):
            try:
                decoded = data.decode("utf-8", errors="replace")
                snippet = decoded[:4000]
                blocks.append({"type": "text", "text": f"ضمیمه فایل متنی {name}:\n{snippet}"})
                history_summaries.append(f"[متن: {name} | {len(decoded)} کاراکتر]")
                continue
            except Exception:
                history_summaries.append(f"[فایل متنی نامعتبر: {name}]")
                continue

        # Fallback: unsupported binary
        history_summaries.append(f"[فایل پشتیبانی‌نشده: {name} | {mime} | {len(data)//1024}KB]")

    return blocks, history_summaries

@app.route("/", methods=["GET", "POST"])
def index():
    if "conversation_history" not in session:
        session["conversation_history"] = []

    response_text = None

    # پاک کردن تاریخچه وقتی کاربر کیس جدید میخواد
    if request.method == "GET" and request.args.get("new_case") == "1":
        session["conversation_history"] = []

    if request.method == "POST":
        role = request.form.get("role", "کاربر")
        text = request.form.get("text", "")
        files = request.files.getlist("files")

        content_blocks, file_msgs = build_anthropic_content(role, text, files)

        session["conversation_history"].append(f"{role}: {text}")
        for fm in file_msgs:
            session["conversation_history"].append(f"📎 {fm}")

        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=900,
            messages=[{"role": "user", "content": content_blocks}]
        )
        response_text = resp.content[0].text
        session["conversation_history"].append(f"🤖 قاضی: {response_text}")

    return render_template(
        "index.html",
        conversation=response_text,
        history=session.get("conversation_history", [])
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
