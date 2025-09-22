# app.py
import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, abort
from anthropic import Anthropic

# -------- configuration --------
APP_TITLE = "شبیه‌ساز قاضی — پرونده‌گردانی"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

if not ANTHROPIC_API_KEY:
    print("⚠️ Warning: ANTHROPIC_API_KEY is not set. The app will return error on verdict generation.")

client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

app = Flask(__name__, template_folder="templates", static_folder="static")

# In-memory store for cases.
# Structure:
# CASES[case_id] = {
#   'id': case_id,
#   'title': str,
#   'judge_notes': str,
#   'plaintiff': {'name': str, 'initial': str, 'history': [entries]},
#   'defendant': {'name': str, 'initial': str, 'history': [entries]},
#   'conversation': [ {'from': 'judge'|'plaintiff'|'defendant', 'text': str} ],
#   'awaiting': None or 'plaintiff' or 'defendant',
#   'status': 'open'|'closed',
#   'verdict': None or str
# }
CASES = {}

# ---------- helpers ----------
def new_case(title, judge_notes, plaintiff_name, plaintiff_initial, defendant_name, defendant_initial):
    cid = uuid.uuid4().hex[:12]
    CASES[cid] = {
        'id': cid,
        'title': title or ("پرونده " + cid),
        'judge_notes': judge_notes or "",
        'plaintiff': {'name': plaintiff_name or "خواهان", 'initial': plaintiff_initial or "", 'history': []},
        'defendant': {'name': defendant_name or "خوانده", 'initial': defendant_initial or "", 'history': []},
        'conversation': [],
        'awaiting': None,
        'status': 'open',
        'verdict': None
    }
    # seed conversation with initial statements (if provided)
    if CASES[cid]['plaintiff']['initial']:
        CASES[cid]['conversation'].append({'from': 'plaintiff', 'text': CASES[cid]['plaintiff']['initial']})
    if CASES[cid]['defendant']['initial']:
        CASES[cid]['conversation'].append({'from': 'defendant', 'text': CASES[cid]['defendant']['initial']})
    return cid

def append_message(case_id, who, text):
    CASES[case_id]['conversation'].append({'from': who, 'text': text})

def build_verdict_prompt(case):
    """
    Create a detailed prompt (Persian) that instructs Claude to draft a formal verdict
    using the conversation and judge's notes. We explicitly ask the model to consider
    the attachments/information and produce a court-style opinion + final order.
    """
    conv_text = ""
    for i, msg in enumerate(case['conversation'], 1):
        sender = {"judge":"قاضی", "plaintiff":"خواهان", "defendant":"خوانده"}.get(msg['from'], msg['from'])
        conv_text += f"{i}. از طرف {sender}:\n{msg['text']}\n\n"

    prompt = f"""
شما نقش یک قاضی دادگاه را دارید. بر اساس اطلاعات و توضیحات زیر، یک رأی رسمی و مکتوب به زبان فارسی تنظیم کنید.
رأی باید شامل: عنوان پرونده، خلاصهٔ وقایع (کوتاه)، بررسی مستندات و استدلال‌ها، بررسی ادله و ایرادات طرفین، دلیل قانونی (ارجاع به قواعد کلی یا مواد قانونی به صورت پیشنهادی)، و در نهایت حکم نهایی (مقررٌ به) و دستور اجرای حکم باشد.
لحن رسمی، حقوقی و قابل استناد باشد؛ اما واضح و منظم با بخش‌بندی شماره‌گذاری شده.

عنوان پرونده: {case['title']}
یادداشت‌های قاضی (در صورت وجود): {case['judge_notes']}

تاریخچۀ گفتگو و توضیحات طرفین:
{conv_text}

--- 
لطفاً ابتدا یک "خلاصهٔ ۳-۵ خطی" از موضوع بیاورید، سپس بخش‌های تحلیل و در انتها حکم نهایی را با عبارت "حکم:" شروع کنید. اگر اطلاعات اضافی لازم است که قاضی باید از طرفین بخواهد، آن‌ها را در انتهای رأی به صورت بولت لیست بیاورید.
"""
    return prompt.strip()

# ---------- routes ----------
@app.route("/", methods=['GET'])
def index():
    # judge starts new case or sees list of cases
    cases_list = list(CASES.values())[::-1]
    return render_template("index.html", page="home", cases=cases_list, app_title=APP_TITLE)

@app.route("/create", methods=['POST'])
def create():
    title = request.form.get("title", "").strip()
    judge_notes = request.form.get("judge_notes", "").strip()
    plaintiff_name = request.form.get("plaintiff_name", "").strip()
    plaintiff_initial = request.form.get("plaintiff_initial", "").strip()
    defendant_name = request.form.get("defendant_name", "").strip()
    defendant_initial = request.form.get("defendant_initial", "").strip()

    cid = new_case(title, judge_notes, plaintiff_name, plaintiff_initial, defendant_name, defendant_initial)
    return redirect(url_for("view_case", case_id=cid))

@app.route("/case/<case_id>", methods=['GET'])
def view_case(case_id):
    case = CASES.get(case_id)
    if not case:
        abort(404)
    return render_template("index.html", page="case", case=case, app_title=APP_TITLE)

@app.route("/request_info/<case_id>", methods=['POST'])
def request_info(case_id):
    case = CASES.get(case_id)
    if not case:
        abort(404)
    # judge selects which party to request more info from
    who = request.form.get("who")
    note = request.form.get("note", "").strip()
    if who not in ("plaintiff", "defendant"):
        abort(400)
    # append a judge message and set awaiting
    append_message(case_id, 'judge', f"درخواست اطلاعات تکمیلی از { 'خواهان' if who=='plaintiff' else 'خوانده' }: {note}")
    case['awaiting'] = who
    return redirect(url_for("view_case", case_id=case_id))

@app.route("/respond/<case_id>/<party>", methods=['GET','POST'])
def respond(case_id, party):
    case = CASES.get(case_id)
    if not case:
        abort(404)
    if party not in ("plaintiff","defendant"):
        abort(400)
    if request.method == 'POST':
        text = request.form.get("response_text", "").strip()
        if not text:
            # nothing provided
            return render_template("index.html", page="respond", case=case, party=party, error="لطفاً متن را وارد کنید.", app_title=APP_TITLE)
        # save response
        append_message(case_id, party, text)
        # clear awaiting if it was for this party
        if case['awaiting'] == party:
            case['awaiting'] = None
        return redirect(url_for("view_case", case_id=case_id))
    # GET -> show response form
    return render_template("index.html", page="respond", case=case, party=party, app_title=APP_TITLE)

@app.route("/issue_verdict/<case_id>", methods=['POST'])
def issue_verdict(case_id):
    case = CASES.get(case_id)
    if not case:
        abort(404)
    # Build prompt and call Claude (if configured)
    prompt = build_verdict_prompt(case)
    if client is None:
        return render_template("index.html", page="case", case=case, error="ANTHROPIC_API_KEY تنظیم نشده است؛ نمی‌توان رأی تولید کرد.", app_title=APP_TITLE)
    try:
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}]
        )
        verdict_text = resp.content[0].text if hasattr(resp, "content") else str(resp)
    except Exception as e:
        verdict_text = f"❌ خطا در تولید رأی: {e}"

    case['verdict'] = verdict_text
    case['status'] = 'closed'
    return redirect(url_for("view_case", case_id=case_id))

# Optional: simple reset (dev)
@app.route("/_reset_all", methods=['POST'])
def reset_all():
    CASES.clear()
    return redirect(url_for("index"))

# run
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
