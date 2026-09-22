import sqlite3
import traceback
from flask import Flask, render_template, request, redirect, url_for, flash, g
import routeros_api

app = Flask(__name__)
app.secret_key = "zenar_secret_key_safe_123"
DATABASE = 'zinar.db'

# ==========================================
# إدارة قاعدة البيانات (SQLite)
# ==========================================
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
        
        # جدول الراوترات
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS routers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                port INTEGER DEFAULT 8728,
                status TEXT DEFAULT 'disconnected'
            )
        ''')
        
        # جدول المشتركين
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                profile TEXT NOT NULL,
                service_type TEXT DEFAULT 'pppoe',
                expiry_date TEXT,
                status TEXT DEFAULT 'active',
                router_id INTEGER
            )
        ''')
        
        # جدول الباقات
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS packages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                rate_limit TEXT NOT NULL,
                price REAL DEFAULT 0
            )
        ''')
        db.commit()

init_db()

# ==========================================
# معالج الأخطاء العالمي
# ==========================================
@app.errorhandler(500)
def internal_error(error):
    err_msg = traceback.format_exc()
    return f"""
    <div dir="rtl" style="padding: 20px; background-color: #f8d7da; color: #721c24; font-family: sans-serif; border-radius: 8px; margin: 20px;">
        <h2>حدث خطأ غير متوقع في الخادم (500 Error):</h2>
        <p>تفاصيل الخطأ البرمجي:</p>
        <pre style="background: #1e1e1e; color: #00ff00; padding: 15px; border-radius: 5px; overflow-x: auto; text-align: left; direction: ltr;">{err_msg}</pre>
    </div>
    """, 500

# ==========================================
# دالة الاتصال بالمايكروتيك (MikroTik API)
# ==========================================
def connect_mikrotik(ip, username, password, port=8728):
    try:
        clean_ip = str(ip).replace('http://', '').replace('https://', '').strip()
        clean_port = int(port) if port else 8728

        connection = routeros_api.RouterOsApiPool(
            clean_ip,
            username=str(username).strip(),
            password=str(password).strip(),
            port=clean_port,
            plaintext_login=True,
            use_ssl=False
        )
        api = connection.get_api()
        return api, connection, None
    except Exception as e:
        return None, None, str(e)

# ==========================================
# المسارات الرئيسية (Routes)
# ==========================================

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
    
    return render_template(
        'dashboard.html',
        routers_count=routers_count,
        packages_count=packages_count,
        sub_count=sub_count,
        active_subs=active_subs,
        subscribers=subscribers
    )

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

        if not name or not ip_address or not username:
            flash('يرجى إدخال جميع الحقول المطلوبة (اسم الراوتر، عنوان IP، واسم المستخدم)', 'danger')
            return redirect(url_for('routers'))

        try:
            cursor.execute(
                'INSERT INTO routers (name, ip_address, username, password, port) VALUES (?, ?, ?, ?, ?)',
                (name, ip_address, username, password, port)
            )
            db.commit()
            flash('تمت إضافة الراوتر بنجاح!', 'success')
        except Exception as e:
            flash(f'فشل حفظ الراوتر: {str(e)}', 'danger')

        return redirect(url_for('routers'))
        
    routers_list = cursor.execute('SELECT * FROM routers').fetchall()
    return render_template('routers.html', routers=routers_list)

@app.route('/routers/test/<int:router_id>')
def test_router(router_id):
    db = get_db()
    cursor = db.cursor()
    router = cursor.execute('SELECT * FROM routers WHERE id = ?', (router_id,)).fetchone()
    
    if not router:
        flash('الراوتر غير موجود!', 'danger')
        return redirect(url_for('routers'))

    api, connection, error = connect_mikrotik(
        router['ip_address'],
        router['username'],
        router['password'],
        router['port']
    )

    if error:
        cursor.execute("UPDATE routers SET status='disconnected' WHERE id=?", (router_id,))
        db.commit()
        flash(f"فشل الاتصال بالمايكروتيك ({router['name']})! السبب: {error}", "danger")
    else:
        try:
            resource_api = api.get_resource('/system/resource')
            resource_api.get()
            cursor.execute("UPDATE routers SET status='connected' WHERE id=?", (router_id,))
            db.commit()
            flash(f"تم الاتصال بنجاح بالمايكروتيك ({router['name']})!", "success")
        except Exception as e:
            cursor.execute("UPDATE routers SET status='disconnected' WHERE id=?", (router_id,))
            db.commit()
            flash(f"فشل أثناء قراءة بيانات المايكروتيك: {str(e)}", "danger")
        finally:
            if connection:
                try:
                    connection.disconnect()
                except Exception:
                    pass

    return redirect(url_for('routers'))

@app.route('/routers/delete/<int:router_id>')
def delete_router(router_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('DELETE FROM routers WHERE id = ?', (router_id,))
    db.commit()
    flash('تم حذف الراوتر بنجاح.', 'success')
    return redirect(url_for('routers'))

@app.route('/subscribers')
def subscribers():
    db = get_db()
    cursor = db.cursor()
    subscribers_list = cursor.execute('SELECT * FROM subscribers ORDER BY id DESC').fetchall()
    return render_template('subscribers.html', subscribers=subscribers_list)

# 6. إضافة مشترك جديد (تم التعديل للتمييز بين Hotspot و PPPoE)
@app.route('/add_subscriber', methods=['GET', 'POST'])
def add_subscriber():
    db = get_db()
    cursor = db.cursor()
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        profile = request.form.get('profile', '').strip()
        service_type = request.form.get('service_type', 'pppoe').strip().lower()
        router_id = request.form.get('router_id')

        if not username or not password or not profile or not router_id:
            flash('الرجاء إدخال كافة بيانات المشترك واختيار الراوتر والبروفايل!', 'danger')
            return redirect(url_for('add_subscriber'))

        router = cursor.execute('SELECT * FROM routers WHERE id = ?', (router_id,)).fetchone()
        
        if not router:
            flash('الرجاء اختيار راوتر صالح!', 'danger')
            return redirect(url_for('add_subscriber'))

        api, connection, error = connect_mikrotik(
            router['ip_address'],
            router['username'],
            router['password'],
            router['port']
        )

        if error:
            flash(f"لم يتم حفظ المشترك! فشل الاتصال بالمايكروتيك: {error}", "danger")
            return redirect(url_for('add_subscriber'))

        try:
            # إضافة المشترك حسب نوع الخدمة
            if service_type == 'hotspot':
                hotspot_user = api.get_resource('/ip/hotspot/user')
                hotspot_user.add(
                    name=str(username),
                    password=str(password),
                    profile=str(profile)
                )
            else:
                ppp_secret = api.get_resource('/ppp/secret')
                valid_ppp_service = service_type if service_type in ['pppoe', 'any', 'l2tp', 'pptp', 'sstp'] else 'any'
                ppp_secret.add(
                    name=str(username),
                    password=str(password),
                    profile=str(profile),
                    service=valid_ppp_service
                )

            cursor.execute(
                'INSERT INTO subscribers (username, password, profile, service_type, router_id, status) VALUES (?, ?, ?, ?, ?, ?)',
                (username, password, profile, service_type, router_id, 'active')
            )
            db.commit()

            flash(f'تمت إضافة المشترك ({username}) بنجاح إلى المايكروتيك وقاعدة البيانات!', 'success')
            return redirect(url_for('subscribers'))

        except Exception as e:
            flash(f"فشل إضافة المشترك داخل المايكروتيك: {str(e)}", "danger")
            return redirect(url_for('add_subscriber'))
        finally:
            if connection:
                try:
                    connection.disconnect()
                except Exception:
                    pass

    routers_list = cursor.execute('SELECT * FROM routers').fetchall()
    packages_list = cursor.execute('SELECT * FROM packages').fetchall()
    return render_template('add_subscriber.html', routers=routers_list, packages=packages_list)

@app.route('/packages', methods=['GET', 'POST'])
def packages():
    db = get_db()
    cursor = db.cursor()
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        rate_limit = request.form.get('rate_limit', '').strip()
        price = request.form.get('price', 0)

        if not name or not rate_limit:
            flash('يرجى كتابة اسم الباقة والسرعة بشكل صحيح!', 'danger')
            return redirect(url_for('packages'))

        try:
            cursor.execute('INSERT INTO packages (name, rate_limit, price) VALUES (?, ?, ?)', (name, rate_limit, price))
            db.commit()
            flash('تمت إضافة الباقة بنجاح!', 'success')
        except Exception as e:
            flash(f'حدث خطأ أثناء حفظ الباقة: {str(e)}', 'danger')

        return redirect(url_for('packages'))

    packages_list = cursor.execute('SELECT * FROM packages').fetchall()
    return render_template('packages.html', packages=packages_list)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
