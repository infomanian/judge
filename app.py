from flask import Flask, render_template, request, jsonify, session
import os
import requests
import json
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')

# Anthropic Claude API configuration
CLAUDE_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"

class CourtCase:
    def __init__(self):
        self.plaintiff_info = ""
        self.plaintiff_documents = ""
        self.defendant_info = ""
        self.defendant_documents = ""
        self.conversation_history = []
        self.status = "initial"  # initial, gathering_info, ready_for_verdict, completed
        self.verdict = ""

def call_claude_api(messages):
    """Call Claude API to get judge's response"""
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': CLAUDE_API_KEY,
        'anthropic-version': '2023-06-01'
    }
    
    data = {
        "model": "claude-3-sonnet-20240229",
        "max_tokens": 1000,
        "messages": messages
    }
    
    try:
        response = requests.post(CLAUDE_API_URL, headers=headers, json=data)
        if response.status_code == 200:
            return response.json()['content'][0]['text']
        else:
            return "خطا در ارتباط با سیستم قضایی. لطفاً دوباره تلاش کنید."
    except Exception as e:
        return f"خطای سیستمی: {str(e)}"

def get_judge_prompt(case, phase):
    """Generate appropriate prompt for judge based on case phase"""
    base_prompt = """شما یک قاضی محترم و با تجربه هستید. وظیفه شما بررسی پرونده و صدور رای عادلانه است.
    لطفاً به زبان فارسی پاسخ دهید و رسمی و محترمانه صحبت کنید."""
    
    if phase == "initial":
        return f"""{base_prompt}
        
یک پرونده جدید به شما ارجاع شده است. اطلاعات اولیه:

شاکی: {case.plaintiff_info}
مدارک شاکی: {case.plaintiff_documents}

متشاکی (مدعی علیه): {case.defendant_info}  
مدارک متشاکی: {case.defendant_documents}

لطفاً اطلاعات را بررسی کنید و اگر برای صدور رای نیاز به توضیحات بیشتری از شاکی یا متشاکی دارید، سوالات مشخص خود را مطرح کنید. اگر اطلاعات کافی است، رای خود را صادر کنید.

در پاسخ خود مشخص کنید که آیا نیاز به اطلاعات بیشتر دارید یا آماده صدور رای هستید."""

    elif phase == "follow_up":
        history = "\n".join([f"{msg['role']}: {msg['content']}" for msg in case.conversation_history[-6:]])
        return f"""{base_prompt}
        
تاریخچه پرونده و مکالمات قبلی:
{history}

لطفاً اطلاعات جدید را بررسی کنید و تصمیم بگیرید که آیا نیاز به اطلاعات بیشتری دارید یا آماده صدور رای نهایی هستید."""

@app.route('/')
def index():
    # Initialize new case in session
    session['case'] = CourtCase().__dict__
    return render_template('index.html')

@app.route('/submit_initial', methods=['POST'])
def submit_initial():
    data = request.json
    
    # Update case with initial information
    case_dict = session.get('case', CourtCase().__dict__)
    case_dict['plaintiff_info'] = data.get('plaintiff_info', '')
    case_dict['plaintiff_documents'] = data.get('plaintiff_documents', '')
    case_dict['defendant_info'] = data.get('defendant_info', '')
    case_dict['defendant_documents'] = data.get('defendant_documents', '')
    case_dict['status'] = 'gathering_info'
    
    session['case'] = case_dict
    
    # Create case object for API call
    case = CourtCase()
    case.__dict__.update(case_dict)
    
    # Get judge's initial response
    prompt = get_judge_prompt(case, "initial")
    messages = [{"role": "user", "content": prompt}]
    
    judge_response = call_claude_api(messages)
    
    # Add to conversation history
    case_dict['conversation_history'].append({
        "role": "judge",
        "content": judge_response,
        "timestamp": datetime.now().isoformat()
    })
    
    session['case'] = case_dict
    
    # Check if judge is ready for verdict
    if any(keyword in judge_response.lower() for keyword in ['رای', 'حکم', 'نهایی', 'صادر']):
        case_dict['status'] = 'completed'
        case_dict['verdict'] = judge_response
        session['case'] = case_dict
    
    return jsonify({
        'success': True,
        'judge_response': judge_response,
        'status': case_dict['status']
    })

@app.route('/submit_followup', methods=['POST'])
def submit_followup():
    data = request.json
    case_dict = session.get('case', {})
    
    if not case_dict:
        return jsonify({'success': False, 'error': 'پرونده یافت نشد'})
    
    # Add user response to history
    case_dict['conversation_history'].append({
        "role": data.get('party', 'user'),
        "content": data.get('response', ''),
        "timestamp": datetime.now().isoformat()
    })
    
    # Create case object for API call
    case = CourtCase()
    case.__dict__.update(case_dict)
    
    # Get judge's response
    prompt = get_judge_prompt(case, "follow_up")
    
    # Prepare messages for API
    messages = []
    for msg in case_dict['conversation_history'][-8:]:  # Last 8 messages for context
        if msg['role'] == 'judge':
            messages.append({"role": "assistant", "content": msg['content']})
        else:
            messages.append({"role": "user", "content": msg['content']})
    
    messages.append({"role": "user", "content": prompt})
    
    judge_response = call_claude_api(messages)
    
    # Add judge response to history
    case_dict['conversation_history'].append({
        "role": "judge", 
        "content": judge_response,
        "timestamp": datetime.now().isoformat()
    })
    
    # Check if judge is ready for verdict
    if any(keyword in judge_response.lower() for keyword in ['رای نهایی', 'حکم نهایی', 'رای صادر', 'نهایتاً']):
        case_dict['status'] = 'completed'
        case_dict['verdict'] = judge_response
    
    session['case'] = case_dict
    
    return jsonify({
        'success': True,
        'judge_response': judge_response,
        'status': case_dict['status']
    })

@app.route('/get_case_status')
def get_case_status():
    case_dict = session.get('case', {})
    return jsonify({
        'status': case_dict.get('status', 'initial'),
        'conversation_history': case_dict.get('conversation_history', []),
        'verdict': case_dict.get('verdict', '')
    })

@app.route('/reset_case', methods=['POST'])
def reset_case():
    session['case'] = CourtCase().__dict__
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)