import os
import base64
from flask import Flask, render_template, request, session
from anthropic import Anthropic

app = Flask(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-1-20250805") 
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
client = Anthropic(api_key=ANTHROPIC_API_KEY)
app.secret_key = os.getenv("SESSION_SECRET", "amir")
# conversation_history = []

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

        #if "conversation_history" not in session:
        #    session["conversation_history"] = []

        session["conversation_history"].append(f"{role}: {text}")

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
