import os
import uuid
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session

try:
    from anthropic import Anthropic
except Exception:
    Anthropic = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

# Simple in-memory store per session
CASE_STORE = {}

def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

def get_case(create_if_missing: bool = True) -> dict:
    case_id = session.get("case_id")
    if case_id is None and create_if_missing:
        case_id = str(uuid.uuid4())
        session["case_id"] = case_id
    if case_id is None:
        return {}
    if case_id not in CASE_STORE and create_if_missing:
        CASE_STORE[case_id] = {
            "plaintiff_submissions": [],
            "defendant_submissions": [],
            "judge_requests": [],  # {target: 'plaintiff'|'defendant', message, ts}
            "verdict": None,
        }
    return CASE_STORE.get(case_id, {})

def reset_case():
    case_id = session.get("case_id")
    if case_id and case_id in CASE_STORE:
        del CASE_STORE[case_id]
    session["case_id"] = str(uuid.uuid4())
    _ = get_case(create_if_missing=True)

def call_claude_for_judge(case: dict) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or Anthropic is None:
        return {
            "action": "request",
            "target": "plaintiff",
            "message": "برای فعال‌سازی قاضی هوشمند، کلید ANTHROPIC_API_KEY را در Render تنظیم کنید.",
        }

    client = Anthropic(api_key=api_key)

    def fmt_entries(entries):
        chunks = []
        for i, e in enumerate(entries, start=1):
            link_part = f"\nلینک/مدرک: {e.get('link')}" if e.get("link") else ""
            chunks.append(f"- نوبت {i} ({e.get('ts')}):\nمتن: {e.get('text')}{link_part}")
        return "\n".join(chunks) if chunks else "(بدون ورودی)"

    plaintiff_text = fmt_entries(case.get("plaintiff_submissions", []))
    defendant_text = fmt_entries(case.get("defendant_submissions", []))

    system_prompt = (
        "شما نقش قاضی را دارید. فقط یکی از دو خروجی زیر را به صورت JSON معتبر و بدون هیچ متن اضافی تولید کنید:\n"
        "1) اگر برای تصمیم‌گیری به اطلاعات بیشتری نیاز است: {\"action\":\"request\",\"target\":\"plaintiff|defendant\",\"message\":\"متن درخواست مشخص، کوتاه و دقیق\"}\n"
        "2) اگر اطلاعات کافی است: {\"action\":\"verdict\",\"verdict\":\"متن رای نهایی کوتاه و صریح\"}\n"
        "قوانین: فقط و فقط JSON معتبر چاپ کن. هیچ تحلیل، مقدمه یا توضیح دیگری مجاز نیست. خروجی باید UTF-8 و فارسی باشد."
    )

    user_prompt = (
        "پرونده فعلی:\n\n"
        "ورودی‌های شاکی:\n" + plaintiff_text + "\n\n"
        "ورودی‌های متشاکی:\n" + defendant_text + "\n\n"
        "اگر نیاز به اطلاعات تکمیلی از یکی خواسته می‌شود، فقط درخواست کوتاه و دقیق بده و مخاطب را مشخص کن.\n"
        "اگر کافی است، رای نهایی کوتاه و صریح بده."
    )

    try:
        msg = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
            max_tokens=400,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text_parts = []
        for block in msg.content:
            if block.type == "text":
                text_parts.append(block.text)
        output = "".join(text_parts).strip()

        data = json.loads(output)
        if not isinstance(data, dict) or "action" not in data:
            raise ValueError("Invalid schema")
        if data["action"] == "request":
            if data.get("target") not in ("plaintiff", "defendant") or not data.get("message"):
                raise ValueError("Invalid request schema")
        elif data["action"] == "verdict":
            if not data.get("verdict"):
                raise ValueError("Invalid verdict schema")
        else:
            raise ValueError("Unknown action")
        return data
    except Exception:
        return {
            "action": "request",
            "target": "plaintiff",
            "message": "سیستم قاضی موقتاً در دسترس نیست. لطفاً توضیحات بیشتری ارائه کنید.",
        }

@app.route("/")
def index():
    case = get_case()
    last_request = case["judge_requests"][-1] if case.get("judge_requests") else None
    return render_template("index.html", case=case, last_request=last_request)

@app.post("/submit/plaintiff")
def submit_plaintiff():
    case = get_case()
    text = (request.form.get("plaintiff_text") or "").strip()
    link = (request.form.get("plaintiff_link") or "").strip()
    if not text and not link:
        return redirect(url_for("index"))
    case["plaintiff_submissions"].append({"text": text, "link": link, "ts": _now_iso()})
    return redirect(url_for("index"))

@app.post("/submit/defendant")
def submit_defendant():
    case = get_case()
    text = (request.form.get("defendant_text") or "").strip()
    link = (request.form.get("defendant_link") or "").strip()
    if not text and not link:
        return redirect(url_for("index"))
    case["defendant_submissions"].append({"text": text, "link": link, "ts": _now_iso()})
    return redirect(url_for("index"))

@app.post("/judge/evaluate")
def judge_evaluate():
    case = get_case()
    result = call_claude_for_judge(case)
    if result.get("action") == "request":
        case["judge_requests"].append({
            "target": result.get("target"),
            "message": result.get("message"),
            "ts": _now_iso(),
        })
    elif result.get("action") == "verdict":
        case["verdict"] = result.get("verdict")
    return redirect(url_for("index"))

@app.post("/judge/reset")
def judge_reset():
    reset_case()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))