import os
import base64
from flask import Flask, render_template, request, session, redirect, url_for
from anthropic import Anthropic

app = Flask(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-1-20250805") 
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
client = Anthropic(api_key=ANTHROPIC_API_KEY)

app.secret_key = os.getenv("SESSION_SECRET", "amir")


def build_user_content(role, text, files):
    """
    آماده‌سازی پیام کاربر شامل متن و فایل‌ها
    """
    content_blocks = [{"type": "text", "text": f"{role}: {text}"}]

    for f in files:
        if f and f.filename:
            file_bytes = f.read()
            f.seek(0)  # ریست کردن بعد از read

            mime = f.mimetype or "application/octet-stream"
            if mime.startswith("image/"):
                # تصویر به صورت بلاک واقعی
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": base64.b64encode(file_bytes).decode("utf-8")
                    }
                })
            else:
                # فایل متنی یا باینری
                try:
                    decoded = file_bytes.decode("utf-8")
                    content_blocks.append({
                        "type": "text",
                        "text": f"[فایل متنی {f.filename}]: {decoded[:500]}..."
                    })
                except:
                    content_blocks.append({
                        "type": "text",
                        "text": f"[فایل باینری {f.filename}]"
                    })
    return content_blocks


@app.route("/", methods=["GET", "POST"])
def index():
    if "conversation_history" not in session:
        session["conversation_history"] = []

    response_text = None

    # شروع پرونده جدید
    if request.method == "GET" and request.args.get("new_case") == "1":
        session["conversation_history"] = []
        return redirect(url_for("index"))

    if request.method == "POST":
        role = request.form.get("role")
        text = request.form.get("text")
        files = request.files.getlist("files")

        # آماده‌سازی ورودی
        user_content = build_user_content(role, text, files)

        # افزودن پیام کاربر به تاریخچه
        history = session.get("conversation_history", [])
        history.append({"role": "user", "content": user_content})
        session["conversation_history"] = history

        # ساختن لیست پیام‌ها
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=800,
            messages=history
        )

        # جمع کردن تمام بلاک‌های متنی
        response_text = "".join(
            block.text for block in resp.content if block.type == "text"
        )

        # افزودن پاسخ قاضی
        history.append({"role": "assistant", "content": [{"type": "text", "text": response_text}]})
        session["conversation_history"] = history

    return render_template(
        "index.html",
        conversation=response_text,
        history=session.get("conversation_history", [])
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
