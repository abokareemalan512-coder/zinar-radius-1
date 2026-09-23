from flask import Flask, request, redirect, session, g
import sqlite3, os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'zinar-secret-2026'
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
    try:
        db.execute('INSERT INTO users (username, password) VALUES (?,?)', ('admin', generate_password_hash('admin123')))
        db.commit()
    except:
        pass
    db.close()

@app.teardown_appcontext
def close_connection(e):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

init_db()

@app.route('/')
def home():
    return redirect('/dashboard')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        db = get_db()
        u = db.execute('SELECT * FROM users WHERE username=?', (request.form['username'],)).fetchone()
        if u and check_password_hash(u['password'], request.form['password']):
            session['user'] = u['username']
            return redirect('/dashboard')
        return "خطأ <a href='/login'>رجوع</a>"
    return '<body style="background:#0f172a;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;font-family:system-ui"><form method="post" style="background:#1e293b;padding:30px;border-radius:12px;text-align:center"><h2>ZINAR NET</h2><input name="username" placeholder="admin" style="width:100%;padding:10px;margin:5px 0"><br><input name="password" type="password" placeholder="admin123" style="width:100%;padding:10px;margin:5px 0"><br><button style="width:100%;padding:10px;background:#0ea5e9;border:0;border-radius:6px">دخول</button></form></body>'

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect('/login')
    db = get_db()
    c = db.execute('SELECT COUNT(*) FROM routers').fetchone()[0]
    return f'<body dir="rtl" style="background:#0f172a;color:#fff;font-family:system-ui;padding:20px"><h1>✅ الداشبورد شغال</h1><p>الراوترات: {c}</p><p>IP: 198.145.118.146 | user: zinar_api</p><a href="/routers" style="background:#0ea5e9;color:#000;padding:10px 20px;border-radius:8px;text-decoration:none">إدارة الراوترات</a> | <a href="/logout" style="color:#94a3b8">خروج</a></body>'

@app.route('/routers', methods=['GET','POST'])
def routers():
    if 'user' not in session:
        return redirect('/login')
    db = get_db()
    msg=""
    if request.method=='POST':
        db.execute('INSERT INTO routers (name, ip, username, password, api_port) VALUES (?,?,?,?,?)',(request.form['name'],request.form['ip'],request.form['username'],request.form['password'],int(request.form['api_port'])))
        db.commit()
        msg='<p style="color:#22c55e">✅ انحفظ</p>'
    rows=""
    for r in db.execute('SELECT * FROM routers').fetchall():
        rows+=f"<tr><td>{r['name']}</td><td>{r['ip']}</td></tr>"
    return f'<body dir="rtl" style="background:#0f172a;color:#fff;font-family:system-ui;padding:20px"><a href="/dashboard">رجوع</a><h2>الراوترات</h2>{msg}<form method="post" style="background:#1e293b;padding:20px;border-radius:12px;max-width:400px"><input name="name" value="زينار" style="width:100%;padding:8px;margin:5px 0"><input name="ip" value="198.145.118.146" style="width:100%;padding:8px;margin:5px 0"><input name="username" value="zinar_api" style="width:100%;padding:8px;margin:5px 0"><input name="password" placeholder="باسورد الراوتر" style="width:100%;padding:8px;margin:5px 0"><input name="api_port" value="8728" style="width:100%;padding:8px;margin:5px 0"><button style="background:#0ea5e9;padding:10px;border:0;border-radius:6px;width:100%">حفظ</button></form><table border=1 style="margin-top:20px;width:100%;border-collapse:collapse"><tr><th>الاسم</th><th>IP</th></tr>{rows}</table></body>'

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
