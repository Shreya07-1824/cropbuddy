from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3, os, random, re
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer
import json
from deep_translator import GoogleTranslator
import requests
from datetime import datetime

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")
serializer = URLSafeTimedSerializer(app.secret_key)

 # ------------------- Translation functions inside init_db -------------------
def load_translations(lang):
        path = os.path.join(BASE_DIR, "backend", "translations", f"{lang}.json")
        if not os.path.exists(path):
            path = os.path.join(BASE_DIR, "backend", "translations", "en.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

def t(key):
        lang = session.get("lang", "en")
        translations = load_translations(lang)
        return translations.get(key, key)
 
@app.context_processor
def inject_translator():
        return dict(t=t)

# DB path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "backend", "database")
DB_PATH = os.path.join(DB_DIR, "cropbuddy.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fullname TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            state TEXT,
            contact TEXT NOT NULL
        )
    """)
    conn.commit()

    cur.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in cur.fetchall()]
    if "otp" not in cols:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN otp TEXT")
            conn.commit()
        except Exception as e:
            print("Could not add otp column:", e)
    conn.close()

init_db()

# ------------------- Home route for language selection -------------------
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        # User selected a language
        lang = request.form.get("language", "en")
        session["lang"] = lang
        return redirect(url_for("register_page"))
    
    # Show language selection page
    return render_template("select_language.html")
# ---------------------------------------------------------------------------

@app.route("/register")
def register_page():
    return render_template("Registration.html")

@app.route("/register", methods=["POST"])
def register():
    fullname = request.form.get("fullname", "").strip()
    email = request.form.get("email", "").strip()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    state = request.form.get("state", "")
    contact = request.form.get("mobile", "").strip()

    if not fullname or not email or not username or not password or not contact:
        return render_template("Registration.html", alert_message="Please fill all required fields.")

    # Password validation: 6+ chars, has letter and number
    if len(password) < 6:
        return render_template("Registration.html", alert_message="Password must be at least 6 characters long")
    
    if not re.search(r'[a-zA-Z]', password):
        return render_template("Registration.html", alert_message="Password must contain at least one letter")
    
    if not re.search(r'\d', password):
        return render_template("Registration.html", alert_message="Password must contain at least one number")

    otp = str(random.randint(1000, 9999))
    session["pending_user"] = {
        "fullname": fullname,
        "email": email,
        "username": username,
        "password": password,
        "state": state,
        "contact": contact,
        "otp": otp
    }

    ok, err = send_email(email, "CropBuddy: Your OTP", f"<p>Your OTP is: <strong>{otp}</strong></p>")
    if ok:
        return render_template("verify_otp.html", alert_message="OTP sent to your email. Enter it here.")
    else:
        return render_template("Registration.html", alert_message=f"Could not send OTP: {err or 'check logs'}")

@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():
    if request.method == "GET":
        return render_template("verify_otp.html")
    
    entered_otp = request.form.get("otp", "").strip()
    pending = session.get("pending_user")
    
    if not pending:
        return render_template("Registration.html", alert_message="Session expired. Register again.")
    
    if not entered_otp:
        return render_template("verify_otp.html", alert_message="Please enter OTP.")
    
    if entered_otp != pending.get("otp"):
        return render_template("verify_otp.html", alert_message="Invalid OTP. Please try again.")
    
    try:
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO users (fullname,email,username,password,state,contact,otp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pending["fullname"], pending["email"], pending["username"],
                 pending["password"], pending["state"], pending["contact"], pending["otp"])
            )
        except sqlite3.IntegrityError as ie:
            conn.close()
            msg = str(ie)
            if "UNIQUE constraint failed" in msg:
                return render_template("verify_otp.html", alert_message="Email or username already registered.")
            return render_template("verify_otp.html", alert_message=f"DB error: {msg}")
        
        conn.commit()
        conn.close()
        session.pop("pending_user", None)
        session["username"] = pending["username"]
        return redirect(url_for("dashboard"))
        
    except Exception as e:
        print("DB insert error:", e)
        return render_template("verify_otp.html", alert_message="Could not save user. Check server logs.")

@app.route("/signin", methods=["GET", "POST"])
def signin():
    if request.method == "GET":
        return render_template("signin.html")
    
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    
    if not username or not password:
        return render_template("signin.html", alert_message="Please enter username and password.")
    
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password)).fetchone()
    conn.close()
    
    if user:
        session["username"] = user["username"]
        return redirect(url_for("dashboard"))
    else:
        return render_template("signin.html", alert_message="Invalid username or password.")
    
@app.route("/set_language/<lang>")
def set_language(lang):
    session["lang"] = lang
    return redirect(request.referrer or url_for("home"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("forgotpassword.html")
    
    email = request.form.get("email", "").strip()
    if not email:
        return render_template("forgotpassword.html", alert_message="Please enter your registered email.")
    
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    conn.close()
    
    if not user:
        return render_template("forgotpassword.html", alert_message="No account found with that email.")
    
    token = serializer.dumps(email, salt="password-reset-salt")
    reset_link = url_for("reset_password", token=token, _external=True)
    html = f"""
      <p>Hello {user['fullname']},</p>
      <p>Click the link below to reset your password (valid 1 hour):</p>
      <p><a href="{reset_link}">{reset_link}</a></p>
    """
    ok, err = send_email(email, "CropBuddy: Password reset link", html)
    if ok:
        return render_template("forgotpassword.html", alert_message="Link sent to your registered email")
    else:
        return render_template("forgotpassword.html", alert_message=f"Failed to send link: {err or 'check logs'}")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        email = serializer.loads(token, salt="password-reset-salt", max_age=int(os.getenv("RESET_TOKEN_EXPIRY", 3600)))
    except Exception:
        return render_template("forgotpassword.html", alert_message="The reset link is invalid or has expired.")
    
    if request.method == "GET":
        return render_template("reset_password.html", token=token)
    
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    
    if not new_password or not confirm:
        return render_template("reset_password.html", alert_message="Fill both password fields.", token=token)
    
    if new_password != confirm:
        return render_template("reset_password.html", alert_message="Passwords do not match.", token=token)
    
    if len(new_password) < 6:
        return render_template("reset_password.html", alert_message="Password must be at least 6 characters.", token=token)
    
    try:
        conn = get_db_connection()
        conn.execute("UPDATE users SET password=? WHERE email=?", (new_password, email))
        conn.commit()
        conn.close()
        return render_template("signin.html", alert_message="Password reset successful. Please sign in.")
    except Exception as e:
        print("Reset password DB error:", e)
        return render_template("reset_password.html", alert_message="Could not update password. Try later.", token=token)

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

@app.route("/logout")
def logout():
    session.pop("username", None)
    return render_template("signin.html", alert_message="Logged out.")

def send_email(to_email, subject, html_content):
    from_email = os.getenv("FROM_EMAIL")
    api_key = os.getenv("SENDGRID_API_KEY")
    if not from_email or not api_key:
        print("SendGrid missing: FROM_EMAIL or SENDGRID_API_KEY not set in .env")
        return False, "SendGrid not configured"
    message = Mail(from_email=from_email, to_emails=to_email, subject=subject, html_content=html_content)
    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        print("SendGrid response:", getattr(response, "status_code", None))
        return True, None
    except Exception as e:
        print("SendGrid error:", e)
        return False, str(e)


# ==================== MANDI PRICES FEATURE - NEW CODE ====================

# AG Marknet API Configuration
AGMARKNET_API_BASE = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
API_KEY = os.getenv("AGMARKNET_API_KEY", "your-api-key-here")  # Add this to your .env file

@app.route('/mandi_prices')
def mandi_prices():
    """Mandi prices page"""
    if 'username' not in session:
        return redirect(url_for('signin'))
    return render_template('mandiprice.html')

@app.route('/api/get-mandi-prices', methods=['POST'])
def get_mandi_prices():
    """
    Fetch real-time mandi prices from AG Marknet API
    Expected JSON payload: {
        "state": "Punjab",
        "district": "Amritsar",
        "commodity": "Wheat" (optional)
    }
    """
    try:
        data = request.get_json()
        state = data.get('state', '')
        district = data.get('district', '')
        commodity = data.get('commodity', '')
        
        # Build API parameters
        params = {
            'api-key': API_KEY,
            'format': 'json',
            'limit': 100
        }
        
        # Add filters based on user input
        filters = {}
        if state:
            filters['state'] = state
        if district:
            filters['district'] = district
        if commodity:
            filters['commodity'] = commodity
            
        if filters:
            params['filters'] = json.dumps(filters)
        
        # Make request to AG Marknet API
        response = requests.get(AGMARKNET_API_BASE, params=params, timeout=10)
        
        if response.status_code == 200:
            api_data = response.json()
            
            # Process and format the data
            records = api_data.get('records', [])
            formatted_data = []
            
            for record in records:
                formatted_data.append({
                    'market': record.get('market', 'N/A'),
                    'district': record.get('district', 'N/A'),
                    'commodity': record.get('commodity', 'N/A'),
                    'min': float(record.get('min_price', 0)),
                    'max': float(record.get('max_price', 0)),
                    'modal': float(record.get('modal_price', 0)),
                    'date': record.get('arrival_date', datetime.now().strftime('%Y-%m-%d'))
                })
            
            return jsonify({
                'success': True,
                'data': formatted_data,
                'count': len(formatted_data)
            })
        else:
            # If API fails, return sample data for testing
            return jsonify({
                'success': True,
                'data': get_sample_mandi_data(district, commodity),
                'count': len(get_sample_mandi_data(district, commodity)),
                'note': 'Using sample data - API key may be invalid'
            })
            
    except requests.exceptions.RequestException as e:
        # Network error - return sample data
        return jsonify({
            'success': True,
            'data': get_sample_mandi_data(data.get('district', ''), data.get('commodity', '')),
            'count': len(get_sample_mandi_data(data.get('district', ''), data.get('commodity', ''))),
            'note': 'Network error - Using sample data'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def get_sample_mandi_data(district='', commodity=''):
    """Generate sample data for testing"""
    sample_data = [
        {'market': 'Amritsar Mandi', 'district': 'Amritsar', 'commodity': 'Wheat', 'min': 2100, 'max': 2300, 'modal': 2200, 'date': '2025-10-05'},
        {'market': 'Rajasansi Market', 'district': 'Amritsar', 'commodity': 'Rice (Basmati)', 'min': 3500, 'max': 3800, 'modal': 3650, 'date': '2025-10-05'},
        {'market': 'Chatiwind Mandi', 'district': 'Amritsar', 'commodity': 'Cotton', 'min': 6800, 'max': 7200, 'modal': 7000, 'date': '2025-10-05'},
        {'market': 'Ludhiana Grain Market', 'district': 'Ludhiana', 'commodity': 'Wheat', 'min': 2050, 'max': 2250, 'modal': 2150, 'date': '2025-10-05'},
        {'market': 'Khanna Mandi', 'district': 'Ludhiana', 'commodity': 'Maize', 'min': 1800, 'max': 2000, 'modal': 1900, 'date': '2025-10-05'},
        {'market': 'Jagraon Market', 'district': 'Ludhiana', 'commodity': 'Rice', 'min': 3400, 'max': 3700, 'modal': 3550, 'date': '2025-10-05'},
        {'market': 'Patiala Mandi', 'district': 'Patiala', 'commodity': 'Wheat', 'min': 2080, 'max': 2280, 'modal': 2180, 'date': '2025-10-05'},
        {'market': 'Nabha Market', 'district': 'Patiala', 'commodity': 'Cotton', 'min': 6900, 'max': 7300, 'modal': 7100, 'date': '2025-10-05'},
        {'market': 'Samana Mandi', 'district': 'Patiala', 'commodity': 'Mustard', 'min': 5200, 'max': 5500, 'modal': 5350, 'date': '2025-10-05'},
    ]
    
    # Filter by district if provided
    if district:
        sample_data = [item for item in sample_data if item['district'] == district]
    
    # Filter by commodity if provided
    if commodity:
        sample_data = [item for item in sample_data if commodity.lower() in item['commodity'].lower()]
    
    return sample_data

@app.route('/api/get-states', methods=['GET'])
def get_states():
    """Get list of states"""
    states = [
        "Punjab", "Haryana", "Uttar Pradesh", "Madhya Pradesh",
        "Maharashtra", "Karnataka", "Tamil Nadu", "Andhra Pradesh",
        "Gujarat", "Rajasthan"
    ]
    return jsonify({'success': True, 'states': states})

@app.route('/api/get-districts', methods=['POST'])
def get_districts():
    """Get districts for a specific state"""
    data = request.get_json()
    state = data.get('state', '')
    
    districts_data = {
        "Punjab": ["Amritsar", "Ludhiana", "Patiala", "Jalandhar", "Bathinda", "Mohali", "Firozpur", "Sangrur", "Hoshiarpur", "Kapurthala"],
        "Haryana": ["Ambala", "Gurugram", "Faridabad", "Hisar", "Karnal", "Panipat", "Rohtak", "Sonipat", "Yamunanagar", "Sirsa"],
        "Uttar Pradesh": ["Lucknow", "Kanpur", "Ghaziabad", "Agra", "Varanasi", "Meerut", "Allahabad", "Bareilly", "Aligarh", "Moradabad"],
        "Madhya Pradesh": ["Bhopal", "Indore", "Jabalpur", "Gwalior", "Ujjain", "Sagar", "Dewas", "Satna", "Ratlam", "Rewa"],
        "Maharashtra": ["Mumbai", "Pune", "Nagpur", "Nashik", "Aurangabad", "Solapur", "Amravati", "Kolhapur", "Sangli", "Jalgaon"],
        "Karnataka": ["Bangalore", "Mysore", "Hubli", "Mangalore", "Belgaum", "Gulbarga", "Davangere", "Bellary", "Bijapur", "Shimoga"],
        "Tamil Nadu": ["Chennai", "Coimbatore", "Madurai", "Tiruchirappalli", "Salem", "Tirunelveli", "Erode", "Vellore", "Thanjavur", "Dindigul"],
        "Andhra Pradesh": ["Visakhapatnam", "Vijayawada", "Guntur", "Nellore", "Kurnool", "Rajahmundry", "Tirupati", "Kadapa", "Kakinada", "Anantapur"],
        "Gujarat": ["Ahmedabad", "Surat", "Vadodara", "Rajkot", "Bhavnagar", "Jamnagar", "Junagadh", "Gandhinagar", "Anand", "Mehsana"],
        "Rajasthan": ["Jaipur", "Jodhpur", "Kota", "Bikaner", "Udaipur", "Ajmer", "Bhilwara", "Alwar", "Bharatpur", "Sikar"]
    }
    
    districts = districts_data.get(state, [])
    return jsonify({'success': True, 'districts': districts})

# ==================== END OF MANDI PRICES FEATURE ====================


if __name__ == "__main__":
    app.run(debug=True)