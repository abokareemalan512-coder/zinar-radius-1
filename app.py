import os
import sqlite3
from flask import Flask, request, redirect, session, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'zinar-2026-secret')
DATABASE = '/tmp/zinar.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS routers (id INTEGER PRIMARY KEY, name TEXT, ip TEXT, username TEXT, password TEXT, api_port INTEGER)')
    db.execute('CREATE TABLE IF NOT EXISTS subscribers (id INTEGER PRIMARY KEY, name TEXT, username TEXT, ip TEXT)')
    try:
        db.execute('INSERT INTO users (username, password) VALUES (?,?)', ('admin', generate_password_hash('admin123')))
        db.commit()
    except: pass
    db.close()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

init_db()

def login_required():
    if 'user' not in session:
        return True
    return False

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
        return "<h3>خطأ بالدخول</h3><a href='/login'>رجوع</a>"
    return """
    <html dir="rtl"><body style="background:#0f172a;color:#fff;font-family:system-ui;display:flex;justify-content:center;align-items:center;height:100vh;margin:0">
    <form method="post" style="background:#1e293b;padding:30px;border-radius:12px;width:300px;text-align:center">
    <h2>دخول زينار نت</h2>
    <input name="username" placeholder="اسم المستخدم" style="width:100%;padding:10px;margin:5px 0;border-radius:6px;border:0" required><br>
    <input name="password" type="password" placeholder="كلمة السر" style="width:100%;padding:10px;margin:5px 0;border-radius:6px;border:0" required><br>
    <button style="width:100%;padding:10px;background:#0ea5e9;border:0;border-radius:8px;margin-top:10px;font-weight:bold;cursor:pointer">دخول</button>
    <p style="font-size:12px;color:#94a3b8;margin-top:10px">admin / admin123</p>
    </form></body></html>
    """

@app.route('/dashboard')
def dashboard():
    if login_required():
        return redirect('/login')
    db = get_db()
    try:
        rc = db.execute('SELECT COUNT(*) FROM routers').fetchone()[0]
    except:
        rc = 0
    return f"""
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>زينار نت</title>
<style>
body{{margin:0;background:#0f172a;color:#fff;font-family:system-ui}}
.header{{background:#1e293b;padding:16px 24px;display:flex;justify-content:space-between}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;padding:20px}}
.card{{background:#1e293b;border:1px solid #334155;border-radius:14px;padding:20px;text-align:center}}
.card a{{display:inline-block;margin-top:12px;background:#0ea5e9;color:#000;padding:8px 16px;border-radius:8px;text-decoration:none;font-weight:700}}
</style></head><body>
<div class="header"><b>🌐 ZINAR NET - Ifrin</b><div>{session['user']} | <a href="/logout" style="color:#94a3b8;text-decoration:none">خروج</a></div></div>
<div class="grid">
<div class="card"><h2>📡 {rc}</h2><p>الراوترات</p><a href="/routers">إدارة</a><br><small style="color:#22c55e">198.145.118.146</small></div>
<div class="card"><h2>👥</h2><p>المشتركين</p><a href="/subscribers">فتح</a></div>
<div class="card"><h2>➕</h2><p>إضافة</p><a href="/add_subscriber">فتح</a></div>
</div>
</body></html>
"""

@app.route('/routers', methods=['GET', 'POST'])
def routers():
    if login_required():
        return redirect('/login')
    db = get_db()
    if request.method == 'POST':
        try:
            db.execute('INSERT INTO routers (name, ip, username, password, api_port) VALUES (?,?,?,?,?)',
                (request.form['name'], request.form['ip'], request.form['username'], request.form['password'], int(request.form.get('api_port', 8728))))
            db.commit()
            msg = "<p style='color:#22c55e'>✅ تم حفظ الراوتر بنجاح</p>"
        except Exception as e:
            msg = f"<p style='color:#ef4444'>❌ خطأ: {e}</p>"
    else:
        msg = ""

    rows = ""
    try:
        all_r = db.execute('SELECT * FROM routers').fetchall()
        for r in all_r:
            rows += f"<tr><td>{r['name']}</td><td>{r['ip']}</td><td>{r['username']}</td><td>{r['api_port']}</td></tr>"
    except:
        rows = ""

    return f"""
    <html lang="ar" dir="rtl"><head><meta charset="UTF-8"><style>
    body{{background:#0f172a;color:#fff;font-family:system-ui;padding:20px}}
    input{{padding:10px;margin:5px;border-radius:6px;border:1px solid #334155;background:#1e293b;color:#fff;width:100%;box-sizing:border-box}}
    button{{padding:10px 20px;background:#0ea5e9;border:0;border-radius:8px;font-weight:700;cursor:pointer}}
    table{{width:100%;border-collapse:collapse;margin-top:20px;background:#1e293b;border-radius:8px;overflow:hidden}}
    td,th{{padding:10px;border-bottom:1px solid #334155;text-align:right}}
    a{{color:#0ea5e9;text-decoration:none}}
    </style></head><body>
    <a href="/dashboard">⬅ رجوع</a>
    <h2>📡 إضافة راوتر</h2>
    {msg}
    <form method="post" style="max-width:400px;background:#1e293b;padding:20px;border-radius:12px">
    <label>الاسم</label><input name="name" value="سيرفر زينار" required>
    <label>IP</label><input name="ip" value="198.145.118.146" required>
    <label>Username</label><input name="username" value="zinar_api" required>
    <label>Password</label><input name="password" type="password" placeholder="كلمة سر الراوتر" required>
    <label>Port</label><input name="api_port" value="8728" required>
    <button type="submit">💾 حفظ</button>
    </form>
    <table><tr><th>الاسم</th><th>IP</th><th>يوزر</th><th>بورت</th></tr>{rows}</table>
    </body></html>
    """

@app.route('/subscribers')
def subscribers():
    if login_required(): return redirect('/login')
    return "<html dir='rtl'><body style='background:#0f172a;color:#fff;padding:20px'><a href='/dashboard'>رجوع</a><h2>المشتركين قريباً</h2></body></html>"

@app.route('/add_subscriber')
def add_sub():
    if login_required(): return redirect('/login')
    return redirect('/dashboard')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
