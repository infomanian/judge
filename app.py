import os
from flask import Flask, render_template, request, session
from anthropic import Anthropic

app = Flask(__name__)
app.secret_key = os.getenv("SESSION_SECRET", "replace-me")

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
# ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-1-20250805") 
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

@app.route("/", methods=["GET", "POST"])
def index():
    # اگه کاربر کیس جدید شروع کرد → تاریخچه پاک بشه
    if request.method == "GET":
        session["conversation_history"] = []
        session["claimant_messages"] = []
        session["defendant_messages"] = []
        return render_template("index.html")

    role = request.form.get("role")
    text = request.form.get("text")
    files = request.files.getlist("files")

    if "conversation_history" not in session:
        session["conversation_history"] = []
        session["claimant_messages"] = []
        session["defendant_messages"] = []

    # متن ورودی رو به تاریخچه اضافه کن
    msg = f"{role}: {text}"
    session["conversation_history"].append(msg)

    if role == "شاکی":
        session["claimant_messages"].append(text)
    elif role == "متشاکی":
        session["defendant_messages"].append(text)

    # پرامپت کامل بسازیم
    prompt = "\n\n".join(session["conversation_history"])

    # پاسخ قاضی
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    response_text = resp.content[0].text

    session["conversation_history"].append(f"🤖 قاضی: {response_text}")

    return render_template(
        "index.html",
        conversation=response_text,
        claimant_history=session["claimant_messages"],
        defendant_history=session["defendant_messages"]
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
