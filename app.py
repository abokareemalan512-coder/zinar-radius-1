import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, flash

app = Flask(__name__)
app.secret_key = 'zinar-premium-2026'

from app.hotspot import hotspot_bp
app.register_blueprint(hotspot_bp)

DATABASE = 'zinar.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS subscribers (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, full_name TEXT, phone TEXT, profile TEXT, service_type TEXT, status TEXT DEFAULT 'active', start_date TEXT, expiry_date TEXT, router_id INTEGER)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS routers (id INTEGER PRIMARY KEY, name TEXT, ip_address TEXT, username TEXT, password TEXT, port INTEGER, status TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS packages (id INTEGER PRIMARY KEY, name TEXT UNIQUE, rate_limit TEXT, price REAL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY, subscriber_id INTEGER, amount REAL, status TEXT, method TEXT, created_at TEXT)''')
    c = conn.execute('SELECT COUNT(*) FROM packages').fetchone()[0]
    if c == 0:
        conn.execute("INSERT INTO packages (name, rate_limit, price) VALUES ('1M','1M/1M',4),('2M','2M/2M',5),('4M','4M/4M',7),('8M','8M/8M',10)")
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def home(): return redirect('/dashboard')

@app.route('/dashboard')
def dashboard():
    conn = get_db()
    sub_count = conn.execute('SELECT COUNT(*) FROM subscribers').fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM subscribers WHERE status='active'").fetchone()[0]
    routers = conn.execute('SELECT COUNT(*) FROM routers').fetchone()[0]
    pkgs = conn.execute('SELECT COUNT(*) FROM packages').fetchone()[0]
    subs = conn.execute('SELECT * FROM subscribers ORDER BY id DESC LIMIT 5').fetchall()
    conn.close()
    return render_template('dashboard.html', sub_count=sub_count, active_subs=active, routers_count=routers, packages_count=pkgs, pending_pays=0, subscribers=subs, sham_account="shamcash-123")

@app.route('/subscribers')
def subs():
    conn = get_db()
    s = conn.execute('SELECT * FROM subscribers ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('subscribers.html', subscribers=s)

@app.route('/add-subscriber', methods=['GET','POST'])
def add_sub():
    conn = get_db()
    pkgs = conn.execute('SELECT * FROM packages').fetchall()
    rtrs = conn.execute('SELECT * FROM routers').fetchall()
    if request.method == 'POST':
        u = request.form['username']; p = request.form['password']
        f = request.form.get('full_name',u); ph = request.form.get('phone','')
        prof = request.form.get('profile','1M'); st = datetime.now().strftime('%Y-%m-%d'); ex = (datetime.now()+timedelta(days=30)).strftime('%Y-%m-%d')
        try:
            conn.execute('INSERT INTO subscribers (username,password,full_name,phone,profile,start_date,expiry_date,status) VALUES (?,?,?,?,?,?,?,?)',(u,p,f,ph,prof,st,ex,'active'))
            conn.commit()
        except: pass
        conn.close()
        return redirect('/subscribers')
    conn.close()
    return render_template('add_subscriber.html', packages=pkgs, routers=rtrs)

@app.route('/subscribers/toggle/<int:id>')
def toggle(id):
    conn = get_db(); s = conn.execute('SELECT status FROM subscribers WHERE id=?',(id,)).fetchone()
    if s:
        ns = 'inactive' if s['status']=='active' else 'active'
        conn.execute('UPDATE subscribers SET status=? WHERE id=?',(ns,id)); conn.commit()
    conn.close(); return redirect('/subscribers')

@app.route('/subscribers/reset/<int:id>')
def reset(id):
    conn = get_db(); ex = (datetime.now()+timedelta(days=30)).strftime('%Y-%m-%d')
    conn.execute('UPDATE subscribers SET expiry_date=?, status=? WHERE id=?',(ex,'active',id)); conn.commit(); conn.close()
    return redirect('/subscribers')

@app.route('/subscribers/delete/<int:id>')
def delete(id):
    conn = get_db(); conn.execute('DELETE FROM subscribers WHERE id=?',(id,)); conn.commit(); conn.close()
    return redirect('/subscribers')

@app.route('/routers', methods=['GET','POST'])
def routers():
    conn = get_db()
    if request.method == 'POST':
        conn.execute('INSERT INTO routers (name,ip_address,username,password,port,status) VALUES (?,?,?,?,?,?)',(request.form['name'],request.form['ip_address'],request.form['username'],request.form.get('password',''),request.form.get('port',8728),'disconnected'))
        conn.commit()
    r = conn.execute('SELECT * FROM routers ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('routers.html', routers=r)

@app.route('/packages', methods=['GET','POST'])
def packages():
    conn = get_db()
    if request.method == 'POST':
        try:
            conn.execute('INSERT INTO packages (name,rate_limit,price) VALUES (?,?,?)',(request.form['name'],request.form['rate_limit'],request.form['price']))
            conn.commit()
        except: pass
    p = conn.execute('SELECT * FROM packages ORDER BY price').fetchall()
    conn.close()
    return render_template('packages.html', packages=p)

@app.route('/payments')
def payments():
    return render_template('payments.html', payments=[], pending_pays=0)

@app.route('/pay')
def pay(): return render_template('pay.html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
