import os
import sqlite3
from flask import Flask, render_template, request, redirect, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'zinar-secret-2026')
DATABASE = 'zinar.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT)''')
        db.execute('''CREATE TABLE IF NOT EXISTS routers
                     (id INTEGER PRIMARY KEY, name TEXT, ip TEXT, username TEXT, password TEXT, api_port INTEGER, status TEXT DEFAULT 'unknown')''')
        db.execute('''CREATE TABLE IF NOT EXISTS subscribers
                     (id INTEGER PRIMARY KEY, name TEXT, username TEXT, password TEXT, ip TEXT, package TEXT, router_id INTEGER)''')
        db.execute('''CREATE TABLE IF NOT EXISTS packages (id INTEGER PRIMARY KEY, name TEXT, speed TEXT, price TEXT)''')
        # انشاء ادمن افتراضي
        try:
            db.execute('INSERT INTO users (username, password) VALUES (?,?)',
                      ('admin', generate_password_hash('admin123')))
            db.commit()
        except: pass

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.route('/')
def index():
    return redirect('/dashboard')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username=?', (request.form['username'],)).fetchone()
        if user and check_password_hash(user['password'], request.form['password']):
            session['user'] = user['username']
            return redirect('/dashboard')
        flash('خطأ بالدخول', 'error')
    return """
    <html dir="rtl"><body style="background:#0f172a;color:#fff;font-family:system-ui;display:flex;justify-content:center;align-items:center;height:100vh">
    <form method="post" style="background:#1e293b;padding:30px;border-radius:12px;width:300px">
    <h2>دخول زينار نت</h2>
    <input name="username" placeholder="اسم المستخدم" style="width:100%;padding:10px;margin:5px 0" required><br>
    <input name="password" type="password" placeholder="كلمة السر" style="width:100%;padding:10px;margin:5px 0" required><br>
    <button style="width:100%;padding:10px;background:#0ea5e9;border:0;border-radius:8px;margin-top:10px">دخول</button>
    <p style="font-size:12px;color:#94a3b8">افتراضي: admin / admin123</p>
    </form></body></html>
    """

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect('/login')
    db = get_db()
    routers_count = db.execute('SELECT COUNT(*) FROM routers').fetchone()[0]
    subs_count = db.execute('SELECT COUNT(*) FROM subscribers').fetchone()[0]
    return f"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>زينار نت - لوحة التحكم</title>
<style>
body{{margin:0;background:#0f172a;color:#fff;font-family:system-ui}}
.header{{background:#1e293b;padding:16px 24px;display:flex;justify-content:space-between;align-items:center}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;padding:20px}}
.card{{background:#1e293b;border:1px solid #334155;border-radius:14px;padding:20px;text-align:center}}
.card a{{display:inline-block;margin-top:12px;background:#0ea5e9;color:#000;padding:8px 16px;border-radius:8px;text-decoration:none;font-weight:700}}
.stat{{font-size:28px;font-weight:800}}
</style>
</head>
<body>
<div class="header"><b>🌐 ZINAR NET - Ifrin</b><div><span style="color:#94a3b8">{session['user']}</span> | <a href="/logout" style="color:#94a3b8;text-decoration:none">خروج</a></div></div>
<div class="grid">
<div class="card"><div class="stat">{routers_count}</div><p>الراوترات</p><a href="/routers">إدارة الراوترات</a><br><small style="color:#22c55e">IP: 198.145.118.146</small></div>
<div class="card"><div class="stat">{subs_count}</div><p>المشتركين</p><a href="/subscribers">إدارة المشتركين</a></div>
<div class="card"><h2>➕</h2><p>إضافة مشترك</p><a href="/add_subscriber">إضافة</a></div>
<div class="card"><h2>📦</h2><p>الباقات</p><a href="/packages">الباقات</a></div>
</div>
</body>
</html>
    """

@app.route('/routers', methods=['GET', 'POST'])
def routers():
    if 'user' not in session:
        return redirect('/login')
    db = get_db()
    if request.method == 'POST':
        try:
            db.execute('INSERT INTO routers (name, ip, username, password, api_port) VALUES (?,?,?,?,?)',
                (request.form['name'], request.form['ip'], request.form['username'], request.form['password'], int(request.form.get('api_port', 8728))))
            db.commit()
            flash('تم حفظ الراوتر ✅', 'success')
        except Exception as e:
            flash(f'خطأ: {e}', 'error')
        return redirect('/routers')

    all_routers = db.execute('SELECT * FROM routers').fetchall()
    rows = ""
    for r in all_routers:
        rows += f"<tr><td>{r['name']}</td><td>{r['ip']}</td><td>{r['username']}</td><td>{r['api_port']}</td><td><span style='color:#22c55e'>محفوظ</span></td></tr>"

    return f"""
    <html lang="ar" dir="rtl"><head><meta charset="UTF-8"><style>
    body{{background:#0f172a;color:#fff;font-family:system-ui;padding:20px}}
    input{{padding:10px;margin:5px;border-radius:6px;border:1px solid #334155;background:#1e293b;color:#fff;width:100%}}
    button{{padding:10px 20px;background:#0ea5e9;border:0;border-radius:8px;font-weight:700;cursor:pointer}}
    table{{width:100%;border-collapse:collapse;margin-top:20px;background:#1e293b;border-radius:8px;overflow:hidden}}
    td,th{{padding:10px;border-bottom:1px solid #334155;text-align:right}}
    a{{color:#0ea5e9;text-decoration:none}}
    </style></head><body>
    <a href="/dashboard">⬅ رجوع للوحة التحكم</a>
    <h2>📡 إضافة راوتر جديد</h2>
    <form method="post" style="max-width:400px;background:#1e293b;padding:20px;border-radius:12px">
    <label>اسم الراوتر</label><input name="name" value="سيرفر زينار" required>
    <label>IP الراوتر</label><input name="ip" value="198.145.118.146" required>
    <label>Username</label><input name="username" value="zinar_api" required>
    <label>Password</label><input name="password" type="password" required>
    <label>Port</label><input name="api_port" value="8728" required>
    <button type="submit">💾 حفظ الراوتر</button>
    </form>
    <h3>الراوترات المحفوظة</h3>
    <table><tr><th>الاسم</th><th>IP</th><th>يوزر</th><th>بورت</th><th>حالة</th></tr>{rows}</table>
    </body></html>
    """

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# باقي الصفحات تعمل redirect للداشبورد مؤقتاً حتى نرجع القوالب
@app.route('/subscribers')
def subscribers():
    if 'user' not in session: return redirect('/login')
    return "<meta http-equiv='refresh' content='0; url=/dashboard'><p>جاري التحميل...</p>"

@app.route('/add_subscriber')
def add_sub():
    if 'user' not in session: return redirect('/login')
    return redirect('/dashboard')

@app.route('/packages')
def packages():
    if 'user' not in session: return redirect('/login')
    return redirect('/dashboard')

# تهيئة قاعدة البيانات اول مرة
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
