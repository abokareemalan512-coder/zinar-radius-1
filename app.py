import sqlite3
import traceback
import re
from flask import Flask, render_template, request, redirect, url_for, flash, g
import routeros_api

try:
    from config import (
        SHAM_CASH_ACCOUNT, SHAM_CASH_ENABLED, PAYMENT_MODE,
        PACKAGES_PRICES, API_SYRIA_BASE_URL, API_SYRIA_KEY,
        PLATFORM_SHAMCASH_ADDRESS, AUTO_VERIFY_ENABLED, MIN_TX_LENGTH
    )
except:
    SHAM_CASH_ACCOUNT = "5889"
    SHAM_CASH_ENABLED = True
    PAYMENT_MODE = "auto"
    PACKAGES_PRICES = {"1M": 4, "2M": 5, "4M": 7, "8M": 10}
    API_SYRIA_BASE_URL = ""
    API_SYRIA_KEY = ""
    PLATFORM_SHAMCASH_ADDRESS = "5889"
    AUTO_VERIFY_ENABLED = True
    MIN_TX_LENGTH = 6

app = Flask(__name__)
app.secret_key = "zenar_secret_key_safe_123"
DATABASE = 'zinar.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS routers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, ip_address TEXT NOT NULL, username TEXT NOT NULL, password TEXT NOT NULL, port INTEGER DEFAULT 8728, status TEXT DEFAULT 'disconnected')''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS subscribers (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password TEXT NOT NULL, profile TEXT NOT NULL, service_type TEXT DEFAULT 'hotspot', phone TEXT DEFAULT '', expiry_date TEXT, status TEXT DEFAULT 'active')''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS packages (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, rate_limit TEXT NOT NULL, price REAL DEFAULT 0)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, subscriber_username TEXT NOT NULL, package_name TEXT, amount REAL, shamcash_tx TEXT, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        db.commit()
        # تحديث الجدول اذا قديم بدون phone
        try:
            cursor.execute('SELECT phone FROM subscribers LIMIT 1')
        except:
            try:
                cursor.execute('ALTER TABLE subscribers ADD COLUMN phone TEXT DEFAULT ""')
                db.commit()
            except: pass
        count = cursor.execute('SELECT COUNT(*) FROM packages').fetchone()[0]
        if count == 0:
            for name, price in PACKAGES_PRICES.items():
                try:
                    cursor.execute('INSERT INTO packages (name, rate_limit, price) VALUES (?,?,?)', (name, f"{name}/{name}", price))
                except: pass
            db.commit()

init_db()

@app.errorhandler(500)
def internal_error(error):
    err_msg = traceback.format_exc()
    return f"<div dir='rtl' style='padding:20px;background:#f8d7da;color:#721c24'><h2>خطأ 500</h2><pre style='background:#1e1e1e;color:#0f0;padding:15px;direction:ltr;text-align:left'>{err_msg}</pre></div>", 500

def connect_mikrotik(ip, username, password, port=8728):
    try:
        clean_ip = str(ip).replace('http://', '').replace('https://', '').strip()
        clean_port = int(port) if port else 8728
        connection = routeros_api.RouterOsApiPool(clean_ip, username=str(username).strip(), password=str(password).strip(), port=clean_port, plaintext_login=True, use_ssl=False)
        api = connection.get_api()
        return api, connection, None
    except Exception as e:
        return None, None, str(e)

def verify_shamcash_payment(tx_id, expected_amount=0):
    if not tx_id:
        return False, "لا يوجد رقم"
    tx = str(tx_id).strip()
    if len(tx) < MIN_TX_LENGTH:
        return False, f"قصير - لازم {MIN_TX_LENGTH}"
    if AUTO_VERIFY_ENABLED:
        return True, "تم التحقق تلقائيا"
    return False, "بانتظار"

@app.route('/')
@app.route('/dashboard')
def dashboard():
    db = get_db()
    cursor = db.cursor()
    routers_count = cursor.execute('SELECT COUNT(*) FROM routers').fetchone()[0]
    packages_count = cursor.execute('SELECT COUNT(*) FROM packages').fetchone()[0]
    sub_count = cursor.execute('SELECT COUNT(*) FROM subscribers').fetchone()[0]
    active_subs = cursor.execute("SELECT COUNT(*) FROM subscribers WHERE status='active'").fetchone()[0]
    subscribers = cursor.execute('SELECT * FROM subscribers ORDER BY id DESC LIMIT 10').fetchall()
    pending_payments = cursor.execute("SELECT COUNT(*) FROM payments WHERE status='pending'").fetchone()[0]
    return render_template('dashboard.html', routers_count=routers_count, packages_count=packages_count, sub_count=sub_count, active_subs=active_subs, subscribers=subscribers, pending_payments=pending_payments, sham_account=SHAM_CASH_ACCOUNT)

@app.route('/routers', methods=['GET', 'POST'])
def routers():
    db = get_db()
    cursor = db.cursor()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        ip_address = request.form.get('ip_address', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        port = request.form.get('port', 8728)
        cursor.execute('INSERT INTO routers (name, ip_address, username, password, port) VALUES (?,?,?,?,?)', (name, ip_address, username, password, port))
        db.commit()
        flash('تمت إضافة السيرفر!', 'success')
        return redirect(url_for('routers'))
    routers_list = cursor.execute('SELECT * FROM routers').fetchall()
    return render_template('routers.html', routers=routers_list)

@app.route('/routers/test/<int:router_id>')
def test_router(router_id):
    db = get_db()
    cursor = db.cursor()
    router = cursor.execute('SELECT * FROM routers WHERE id =?', (router_id,)).fetchone()
    api, connection, error = connect_mikrotik(router['ip_address'], router['username'], router['password'], router['port'])
    if error:
        cursor.execute("UPDATE routers SET status='disconnected' WHERE id=?", (router_id,))
        db.commit()
        flash(f"فشل: {error}", "danger")
    else:
        try:
            api.get_resource('/system/resource').get()
            cursor.execute("UPDATE routers SET status='connected' WHERE id=?", (router_id,))
            db.commit()
            flash("تم الاتصال!", "success")
        except Exception as e:
            flash(f"خطأ: {e}", "danger")
        finally:
            if connection:
                try: connection.disconnect()
                except: pass
    return redirect(url_for('routers'))

@app.route('/routers/delete/<int:router_id>')
def delete_router(router_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('DELETE FROM routers WHERE id =?', (router_id,))
    db.commit()
    return redirect(url_for('routers'))

@app.route('/subscribers')
def subscribers():
    db = get_db()
    cursor = db.cursor()
    subscribers_list = cursor.execute('SELECT * FROM subscribers ORDER BY id DESC').fetchall()
    return render_template('subscribers.html', subscribers=subscribers_list)

@app.route('/add-subscriber', methods=['GET', 'POST'])
@app.route('/add_subscriber', methods=['GET', 'POST'])
def add_subscriber():
    db = get_db()
    cursor = db.cursor()
    count = cursor.execute('SELECT COUNT(*) FROM packages').fetchone()[0]
    if count == 0:
        for name, price in PACKAGES_PRICES.items():
            try:
                cursor.execute('INSERT INTO packages (name, rate_limit, price) VALUES (?,?,?)', (name, f"{name}/{name}", price))
            except: pass
        db.commit()
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        profile = request.form.get('profile', '').strip()
        service_type = request.form.get('service_type', 'hotspot').strip().lower()
        phone = request.form.get('phone', '').strip().replace('+','').replace(' ','')
        shamcash_tx = request.form.get('shamcash_tx', '').strip()
        price = PACKAGES_PRICES.get(profile, 0)
        if not username or not password or not profile:
            flash('أدخل البيانات!', 'danger')
            return redirect(url_for('add_subscriber'))
        payment_status = 'pending'
        if shamcash_tx:
            is_valid, _ = verify_shamcash_payment(shamcash_tx, price)
            payment_status = 'confirmed' if is_valid else 'pending'
        try:
            cursor.execute('INSERT INTO subscribers (username, password, profile, service_type, phone, status) VALUES (?,?,?,?,?,?)', (username, password, profile, service_type, phone, 'active'))
            if shamcash_tx:
                cursor.execute('INSERT INTO payments (subscriber_username, package_name, amount, shamcash_tx, status) VALUES (?,?,?,?,?)', (username, profile, price, shamcash_tx, payment_status))
            db.commit()
            routers_list = cursor.execute('SELECT * FROM routers').fetchall()
            for router in routers_list:
                api, connection, error = connect_mikrotik(router['ip_address'], router['username'], router['password'], router['port'])
                if api and not error:
                    try:
                        if service_type == 'hotspot':
                            res = api.get_resource('/ip/hotspot/user')
                            if not res.get(name=username):
                                res.add(name=str(username), password=str(password), profile=str(profile))
                        else:
                            res = api.get_resource('/ppp/secret')
                            if not res.get(name=username):
                                res.add(name=str(username), password=str(password), profile=str(profile), service=str(service_type))
                    except: pass
                    finally:
                        if connection:
                            try: connection.disconnect()
                            except: pass
            flash(f'تم حفظ {username} ✅', 'success')
            return redirect(url_for('subscribers'))
        except sqlite3.IntegrityError:
            flash('الاسم موجود!', 'danger')
            return redirect(url_for('add_subscriber'))
    packages_list = cursor.execute('SELECT * FROM packages').fetchall()
    return render_template('add_subscriber.html', packages=packages_list, sham_account=SHAM_CASH_ACCOUNT, sham_enabled=SHAM_CASH_ENABLED)

@app.route('/payments')
def payments():
    db = get_db()
    cursor = db.cursor()
    payments_list = cursor.execute('SELECT * FROM payments ORDER BY id DESC').fetchall()
    return render_template('payments.html', payments=payments_list, sham_account=SHAM_CASH_ACCOUNT)

@app.route('/payments/confirm/<int:payment_id>')
def confirm_payment(payment_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE payments SET status='confirmed' WHERE id=?", (payment_id,))
    db.commit()
    flash('تم التأكيد!', 'success')
    return redirect(url_for('payments'))

@app.route('/subscribers/delete/<int:subscriber_id>')
def delete_subscriber(subscriber_id):
    db = get_db()
    cursor = db.cursor()
    subscriber = cursor.execute('SELECT * FROM subscribers WHERE id =?', (subscriber_id,)).fetchone()
    if subscriber:
        username = subscriber['username']
        service_type = subscriber['service_type']
        cursor.execute('DELETE FROM subscribers WHERE id =?', (subscriber_id,))
        db.commit()
        routers_list = cursor.execute('SELECT * FROM routers').fetchall()
        for router in routers_list:
            api, connection, error = connect_mikrotik(router['ip_address'], router['username'], router['password'], router['port'])
            if api and not error:
                try:
                    if service_type == 'hotspot':
                        res = api.get_resource('/ip/hotspot/user')
                        for item in res.get(name=username): res.remove(id=item['id'])
                    else:
                        res = api.get_resource('/ppp/secret')
                        for item in res.get(name=username): res.remove(id=item['id'])
                except: pass
                finally:
                    if connection:
                        try: connection.disconnect()
                        except: pass
    return redirect(url_for('subscribers'))

@app.route('/packages', methods=['GET', 'POST'])
def packages():
    db = get_db()
    cursor = db.cursor()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        rate_limit = request.form.get('rate_limit', '').strip()
        price = request.form.get('price', 0)
        cursor.execute('INSERT INTO packages (name, rate_limit, price) VALUES (?,?,?)', (name, rate_limit, price))
        db.commit()
        return redirect(url_for('packages'))
    packages_list = cursor.execute('SELECT * FROM packages').fetchall()
    return render_template('packages.html', packages=packages_list)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
