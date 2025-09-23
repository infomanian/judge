import os
import base64
from flask import Flask, render_template, request
from anthropic import Anthropic

app = Flask(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = "claude-3-sonnet-20240229"
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

@app.route("/", methods=["GET", "POST"])
def index():
    global conversation_history
    response_text = None
    if request.method == "POST":
        role = request.form.get("role")
        text = request.form.get("text")
        files = request.files.getlist("files")
        user_input = build_prompt(role, text, files)
        conversation_history.append(user_input)
        prompt = "\n\n".join(conversation_history)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = resp.content[0].text
        conversation_history.append(f"🤖 قاضی: {response_text}")
    return render_template("index.html", conversation=response_text, history=conversation_history)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
