import sqlite3
import traceback
from flask import Flask, render_template, request, redirect, url_for, flash, g
import routeros_api

app = Flask(__name__)
app.secret_key = "zenar_secret_key_safe_123"
DATABASE = 'zinar.db'

# --- ملف قابل للتحديث 100% ---
try:
    from config import SHAM_CASH
except:
    SHAM_CASH = {
        "account": "حط حسابك شام كاش هون",
        "mode": "manual",
        "packages": {"1M": 4, "2M": 5, "3M": 6, "6M": 8}
    }

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
        cursor.execute('''CREATE TABLE IF NOT EXISTS subscribers (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password TEXT NOT NULL, profile TEXT NOT NULL, service_type TEXT DEFAULT 'hotspot', expiry_date TEXT, status TEXT DEFAULT 'active')''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS packages (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, rate_limit TEXT NOT NULL, price REAL DEFAULT 0)''')
        # جدول مدفوعات شام كاش - قابل للتحديث
        cursor.execute('''CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, package TEXT, price REAL, sham_tx TEXT, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        db.commit()

init_db()

#... نفس دالة connect_mikrotik عندك...

def connect_mikrotik(ip, username, password, port=8728):
    try:
        clean_ip = str(ip).replace('http://', '').replace('https://', '').strip()
        clean_port = int(port) if port else 8728
        connection = routeros_api.RouterOsApiPool(clean_ip, username=str(username).strip(), password=str(password).strip(), port=clean_port, plaintext_login=True, use_ssl=False)
        api = connection.get_api()
        return api, connection, None
    except Exception as e:
        return None, None, str(e)

# باقي الروتات تبعك نفسها...

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
    return render_template('dashboard.html', routers_count=routers_count, packages_count=packages_count, sub_count=sub_count, active_subs=active_subs, subscribers=subscribers)

# --- الحل للـ 404: ندعم الرابطين ---
@app.route('/add_subscriber', methods=['GET', 'POST'])
@app.route('/add-subscriber', methods=['GET', 'POST'])
def add_subscriber():
    db = get_db()
    cursor = db.cursor()
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        profile = request.form.get('profile', '').strip()
        service_type = request.form.get('service_type', 'hotspot').strip().lower()
        package_price = request.form.get('package_price', '') # من شام كاش
        sham_tx = request.form.get('sham_tx', '').strip()

        if not username or not password or not profile:
            flash('الرجاء إدخال كافة بيانات المشترك!', 'danger')
            return redirect(url_for('add_subscriber'))

        try:
            cursor.execute('INSERT INTO subscribers (username, password, profile, service_type, status) VALUES (?,?,?,?,?)', (username, password, profile, service_type, 'active'))
            db.commit()

            # حفظ عملية شام كاش اذا موجودة
            if sham_tx:
                price = SHAM_CASH['packages'].get(profile, 0)
                cursor.execute('INSERT INTO payments (username, package, price, sham_tx, status) VALUES (?,?,?,?,?)', (username, profile, price, sham_tx, 'pending'))
                db.commit()
                flash(f'تم حفظ المشترك وطلب دفع شام كاش {sham_tx} - بانتظار تأكيدك', 'warning')
            else:
                flash(f'تمت إضافة المشترك ({username}) بنجاح!', 'success')
            return redirect(url_for('subscribers'))
        except Exception as e:
            flash(f"خطأ: {str(e)}", "danger")
            return redirect(url_for('add_subscriber'))

    packages_list = cursor.execute('SELECT * FROM packages').fetchall()
    # نمرر إعدادات شام كاش للقالب - قابل للتحديث
    return render_template('add_subscriber.html', packages=packages_list, sham=SHAM_CASH)

@app.route('/payments')
def payments_list():
    db = get_db()
    payments = db.execute('SELECT * FROM payments ORDER BY id DESC').fetchall()
    return render_template('payments.html', payments=payments)

#... باقي كودك routers, subscribers, packages نفسه...
