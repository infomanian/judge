import os
import base64
from flask import Flask, render_template, request
from anthropic import Anthropic
from flask import Flask, render_template, request, session

app = Flask(__name__)

app.secret_key = os.getenv("SESSION_SECRET", "amir")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-1-20250805") 
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

client = Anthropic(api_key=ANTHROPIC_API_KEY)

conversation_history = []

def build_prompt(role, text, files):
    file_descriptions = []
    for f in files:
        if f and f.filename:
            content = f.read()
            mime = f.mimetype or "application/octet-stream"
            if mime.startswith("image/"):
                file_descriptions.append(f"[تصویر آپلود شد: {f.filename}]")
            else:
                try:
                    decoded = content.decode("utf-8")
                    file_descriptions.append(f"[فایل متنی {f.filename}: {decoded[:500]}...]")
                except:
                    file_descriptions.append(f"[فایل باینری {f.filename}]")
    return f"👤 {role}: {text}\nمدارک: {'; '.join(file_descriptions) if file_descriptions else 'بدون مدرک'}"

if "conversation_history" not in session:
    session["conversation_history"] = []

if request.method == "POST":
    role = request.form.get("role")
    text = request.form.get("text")
    files = request.files.getlist("files")
    user_input = build_prompt(role, text, files)

    # ذخیره پیام به صورت دیکشنری
    session["conversation_history"].append({"role": role, "text": user_input})

    # ساخت prompt برای مدل
    prompt = "\n\n".join([f"{msg['role']}: {msg['text']}" for msg in session["conversation_history"]])
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    response_text = resp.content[0].text
    # ذخیره پاسخ قاضی
    session["conversation_history"].append({"role": "قاضی", "text": response_text})


@app.route("/", methods=["GET", "POST"])
def index():
    if "conversation_history" not in session:
        session["conversation_history"] = []

    response_text = None

    # پاک کردن تاریخچه وقتی کاربر کیس جدید میخواد
    if request.method == "GET" and request.args.get("new_case") == "1":
        session["conversation_history"] = []

    if request.method == "POST":
        role = request.form.get("role")
        text = request.form.get("text")
        files = request.files.getlist("files")
        user_input = build_prompt(role, text, files)

        session["conversation_history"].append(user_input)
        prompt = "\n\n".join(session["conversation_history"])
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
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
