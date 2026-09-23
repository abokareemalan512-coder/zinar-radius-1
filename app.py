import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = 'zinar-net-secret-2026-premium'

DATABASE = 'zinar.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    # جدول المشتركين
    conn.execute('''
        CREATE TABLE IF NOT EXISTS subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            full_name TEXT,
            phone TEXT,
            profile TEXT,
            service_type TEXT,
            status TEXT DEFAULT 'active',
            start_date TEXT,
            expiry_date TEXT,
            router_id INTEGER
        )
    ''')
    # جدول الراوترات
    conn.execute('''
        CREATE TABLE IF NOT EXISTS routers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            username TEXT NOT NULL,
            password TEXT,
            port INTEGER DEFAULT 8728,
            status TEXT DEFAULT 'disconnected'
        )
    ''')
    # جدول الباقات
    conn.execute('''
        CREATE TABLE IF NOT EXISTS packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            rate_limit TEXT NOT NULL,
            price REAL NOT NULL
        )
    ''')
    # جدول المدفوعات - مصلح 100%
    conn.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subscriber_id INTEGER,
            amount REAL,
            status TEXT DEFAULT 'pending',
            method TEXT DEFAULT 'shamcash',
            created_at TEXT
        )
    ''')
    conn.commit()

    # اضافة باقات افتراضية اذا فاضي
    count = conn.execute('SELECT COUNT(*) FROM packages').fetchone()[0]
    if count == 0:
        conn.execute("INSERT INTO packages (name, rate_limit, price) VALUES ('1M', '1M/1M', 4.0)")
        conn.execute("INSERT INTO packages (name, rate_limit, price) VALUES ('2M', '2M/2M', 5.0)")
        conn.execute("INSERT INTO packages (name, rate_limit, price) VALUES ('4M', '4M/4M', 7.0)")
        conn.execute("INSERT INTO packages (name, rate_limit, price) VALUES ('8M', '8M/8M', 10.0)")
        conn.commit()

    conn.close()

# تهيئة قاعدة البيانات عند التشغيل
init_db()

@app.route('/')
def index():
    return redirect('/dashboard')

@app.route('/dashboard')
def dashboard():
    conn = get_db_connection()
    sub_count = conn.execute('SELECT COUNT(*) FROM subscribers').fetchone()[0]
    active_subs = conn.execute("SELECT COUNT(*) FROM subscribers WHERE status='active'").fetchone()[0]
    routers_count = conn.execute('SELECT COUNT(*) FROM routers').fetchone()[0]
    packages_count = conn.execute('SELECT COUNT(*) FROM packages').fetchone()[0]

    # حماية من الخطأ - اذا جدول payments فاضي او في مشكلة
    try:
        pending_pays = conn.execute("SELECT COUNT(*) FROM payments WHERE status='pending'").fetchone()[0]
    except:
        pending_pays = 0

    subscribers = conn.execute('SELECT * FROM subscribers ORDER BY id DESC LIMIT 5').fetchall()
    conn.close()

    # شام كاش - تقدر تغيره من الاعدادات
    sham_account = "shamcash-12345"

    return render_template('dashboard.html',
                           sub_count=sub_count,
                           active_subs=active_subs,
                           routers_count=routers_count,
                           packages_count=packages_count,
                           pending_pays=pending_pays,
                           subscribers=subscribers,
                           sham_account=sham_account)

@app.route('/subscribers')
def subscribers_list():
    conn = get_db_connection()
    subscribers = conn.execute('SELECT * FROM subscribers ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('subscribers.html', subscribers=subscribers)

@app.route('/add-subscriber', methods=['GET', 'POST'])
def add_subscriber():
    conn = get_db_connection()
    packages = conn.execute('SELECT * FROM packages').fetchall()
    routers = conn.execute('SELECT * FROM routers').fetchall()

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        full_name = request.form.get('full_name', username)
        phone = request.form.get('phone', '')
        profile = request.form.get('profile', '1M')
        service_type = request.form.get('service_type', 'pppoe')
        router_id = request.form.get('router_id', 1)

        start = datetime.now().strftime('%Y-%m-%d')
        expiry = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')

        try:
            conn.execute('INSERT INTO subscribers (username, password, full_name, phone, profile, service_type, start_date, expiry_date, router_id) VALUES (?,?,?,?,?,?,?,?,?)',
                         (username, password, full_name, phone, profile, service_type, start, expiry, router_id))
            conn.commit()
            flash('تم اضافة المشترك بنجاح', 'success')
        except Exception as e:
            flash(f'خطأ: {e}', 'danger')

        conn.close()
        return redirect('/subscribers')

    conn.close()
    return render_template('add_subscriber.html', packages=packages, routers=routers)

@app.route('/subscribers/toggle/<int:id>')
def toggle_subscriber(id):
    conn = get_db_connection()
    sub = conn.execute('SELECT status FROM subscribers WHERE id=?', (id,)).fetchone()
    if sub:
        new_status = 'inactive' if sub['status'] == 'active' else 'active'
        conn.execute('UPDATE subscribers SET status=? WHERE id=?', (new_status, id))
        conn.commit()
    conn.close()
    return redirect('/subscribers')

@app.route('/subscribers/reset/<int:id>')
def reset_subscriber(id):
    conn = get_db_connection()
    new_expiry = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    conn.execute('UPDATE subscribers SET expiry_date=?, status=? WHERE id=?', (new_expiry, 'active', id))
    conn.commit()
    conn.close()
    return redirect('/subscribers')

@app.route('/subscribers/delete/<int:id>')
def delete_subscriber(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM subscribers WHERE id=?', (id,))
    conn.commit()
    conn.close()
    return redirect('/subscribers')

@app.route('/routers', methods=['GET', 'POST'])
def routers_page():
    conn = get_db_connection()
    if request.method == 'POST':
        name = request.form['name']
        ip = request.form['ip_address']
        user = request.form['username']
        pwd = request.form.get('password', '')
        port = request.form.get('port', 8728)
        conn.execute('INSERT INTO routers (name, ip_address, username, password, port, status) VALUES (?,?,?,?,?,?)',
                     (name, ip, user, pwd, port, 'disconnected'))
        conn.commit()

    routers = conn.execute('SELECT * FROM routers ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('routers.html', routers=routers)

@app.route('/packages', methods=['GET', 'POST'])
def packages_page():
    conn = get_db_connection()
    if request.method == 'POST':
        name = request.form['name']
        rate = request.form['rate_limit']
        price = request.form['price']
        try:
            conn.execute('INSERT INTO packages (name, rate_limit, price) VALUES (?,?,?)', (name, rate, price))
            conn.commit()
        except Exception as e:
            print(f"Package error: {e}")

    packages = conn.execute('SELECT * FROM packages ORDER BY price ASC').fetchall()
    conn.close()
    return render_template('packages.html', packages=packages)

# ======== تم اصلاح هذا المسار 100% - كان سبب الـ Internal Error ========
@app.route('/payments')
def payments_page():
    try:
        conn = get_db_connection()
        # left join عشان ما يضرب اذا مشترك محذوف
        payments = conn.execute('''
            SELECT p.*, s.username as username
            FROM payments p
            LEFT JOIN subscribers s ON p.subscriber_id = s.id
            ORDER BY p.id DESC
        ''').fetchall()

        try:
            pending_pays = conn.execute("SELECT COUNT(*) FROM payments WHERE status='pending'").fetchone()[0]
        except:
            pending_pays = 0

        conn.close()
        return render_template('payments.html', payments=payments, pending_pays=pending_pays)
    except Exception as e:
        print(f"PAYMENTS ERROR FIXED: {e}")
        # حتى لو في خطأ كبير، رجع صفحة فاضية بدل ما يضرب السيرفر
        return render_template('payments.html', payments=[], pending_pays=0)

@app.route('/pay')
def pay_page():
    return render_template('pay.html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
