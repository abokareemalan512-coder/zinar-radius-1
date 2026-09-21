import os
import random
import string
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
import routeros_api

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'zinar-secret-key-123')

database_url = os.environ.get('DATABASE_URL', 'sqlite:///zinar.db')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

def t(key):
    translations = {
        'brand_sub': 'نظام إدارة المشتركين',
        'dashboard': 'لوحة التحكم',
        'routers': 'الراوترات',
        'subscribers': 'المشتركين',
        'add_subscriber': 'إضافة مشترك',
        'login': 'تسجيل الدخول'
    }
    return translations.get(key, key)

app.jinja_env.globals['t'] = t

# نماذج قاعدة البيانات
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, default='admin')
    password = db.Column(db.String(100), nullable=False, default='admin')

class Router(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(50), nullable=False)
    username = db.Column(db.String(50), nullable=False)
    password = db.Column(db.String(50), nullable=True)
    port = db.Column(db.Integer, default=8728)

class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    service_type = db.Column(db.String(20), default='PPPoE')
    profile = db.Column(db.String(50), nullable=False, default='Default')
    phone = db.Column(db.String(30), nullable=True)
    expiry_date = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), default='active')

# التهيئة والتأكد من وجود حساب Admin افتراضي
with app.app_context():
    try:
        db.create_all()
        admin_account = Admin.query.first()
        if not admin_account:
            default_admin = Admin(username='admin', password='admin')
            db.session.add(default_admin)
            db.session.commit()
    except Exception as e:
        print(f"Database setup note: {e}")

def generate_random_str(length=6):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

# دالة مزامنة الحسابات مع User Manager في السيرفر الرئيسي
def sync_userman(username, password, action='add'):
    # جلب بيانات السيرفر الأول من قاعدة البيانات أو استخدام الإعدادات الافتراضية
    main_router = Router.query.first()
    router_ip = main_router.ip_address if main_router else "198.145.118.146"
    api_user = main_router.username if main_router else "admin"
    api_pass = main_router.password if (main_router and main_router.password) else ""
    api_port = main_router.port if main_router else 8728

    try:
        connection = routeros_api.RouterOsApiPool(
            router_ip,
            username=api_user,
            password=api_pass,
            port=api_port,
            plaintext_login=True
        )
        api = connection.get_api()
        userman_users = api.get_resource('/tool/user-manager/user')

        if action == 'add':
            existing = userman_users.get(username=username)
            if not existing:
                userman_users.add(customer='admin', username=username, password=password)
        elif action == 'delete':
            existing = userman_users.get(username=username)
            if existing:
                userman_users.remove(id=existing[0]['.id'])

        connection.disconnect()
        return True
    except Exception as e:
        print(f"MikroTik API Sync Error: {e}")
        return False

# المسارات
@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        user_input = request.form.get('username')
        pass_input = request.form.get('password')
        admin_account = Admin.query.first()
        if admin_account and user_input == admin_account.username and pass_input == admin_account.password:
            return redirect(url_for('dashboard'))
        else:
            error = "اسم المستخدم أو كلمة المرور غير صحيحة"
    return render_template('login.html', error=error)

@app.route('/admin_settings', methods=['GET', 'POST'])
def admin_settings():
    admin_account = Admin.query.first()
    if not admin_account:
        admin_account = Admin(username='admin', password='admin')
        db.session.add(admin_account)
        db.session.commit()

    message = None
    error = None
    if request.method == 'POST':
        new_username = request.form.get('username')
        new_password = request.form.get('password')
        if new_username and new_password:
            try:
                admin_account.username = new_username
                admin_account.password = new_password
                db.session.commit()
                message = "تم تعديل اسم المستخدم وكلمة المرور بنجاح!"
            except Exception as e:
                db.session.rollback()
                error = "حدث خطأ أثناء تقيد البيانات."
        else:
            error = "جميع الحقول مطلوبة."

    return render_template('admin_settings.html', admin=admin_account, message=message, error=error)

@app.route('/dashboard')
def dashboard():
    routers_count = Router.query.count()
    sub_count = Subscriber.query.count()
    active_subs = Subscriber.query.filter_by(status='active').count()
    subscribers = Subscriber.query.order_by(Subscriber.id.desc()).all()
    admin_account = Admin.query.first()

    return render_template(
        'dashboard.html',
        routers_count=routers_count,
        sub_count=sub_count,
        active_subs=active_subs,
        subscribers=subscribers,
        admin_account=admin_account
    )

@app.route('/routers', methods=['GET', 'POST'])
def routers():
    if request.method == 'POST':
        name = request.form.get('name')
        ip_address = request.form.get('ip_address')
        username = request.form.get('username')
        password = request.form.get('password', '')
        port_val = request.form.get('port', 8728)
        try:
            port_num = int(port_val) if port_val else 8728
        except ValueError:
            port_num = 8728

        if name and ip_address:
            try:
                new_router = Router(
                    name=name,
                    ip_address=ip_address,
                    username=username,
                    password=password,
                    port=port_num
                )
                db.session.add(new_router)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
        return redirect(url_for('routers'))
    
    routers_list = Router.query.all()
    return render_template('routers.html', routers=routers_list)

@app.route('/delete_router/<int:id>')
def delete_router(id):
    try:
        router = Router.query.get_or_404(id)
        db.session.delete(router)
        db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('routers'))

@app.route('/subscribers')
def subscribers():
    subscribers_list = Subscriber.query.order_by(Subscriber.id.desc()).all()
    return render_template('subscribers.html', subscribers=subscribers_list)

@app.route('/add_subscriber', methods=['GET', 'POST'])
def add_subscriber():
    if request.method == 'POST':
        mode = request.form.get('mode', 'single')
        service_type = request.form.get('service_type', 'PPPoE')
        profile = request.form.get('profile', 'Default')
        expiry_date = request.form.get('expiry_date', '')

        if not expiry_date and service_type == 'PPPoE':
            next_month = datetime.now() + timedelta(days=30)
            expiry_date = next_month.strftime('%Y-%m-%d')

        if mode == 'single':
            username = request.form.get('username')
            password = request.form.get('password')
            phone = request.form.get('phone', '')
            if username and password:
                try:
                    sub = Subscriber(
                        username=username,
                        password=password,
                        service_type=service_type,
                        profile=profile,
                        phone=phone,
                        expiry_date=expiry_date
                    )
                    db.session.add(sub)
                    db.session.commit()
                    
                    # إرسال الحساب مباشرة للسيرفر الأول (User Manager)
                    sync_userman(username, password, action='add')
                except Exception:
                    db.session.rollback()

        elif mode == 'bulk':
            try:
                count = int(request.form.get('count', 10))
            except ValueError:
                count = 10
            
            prefix = request.form.get('prefix', '')
            try:
                pass_len = int(request.form.get('password_length', 6))
            except ValueError:
                pass_len = 6

            for _ in range(count):
                u_rand = generate_random_str(5)
                p_rand = generate_random_str(pass_len)
                uname = f"{prefix}{u_rand}"
                try:
                    sub = Subscriber(
                        username=uname,
                        password=p_rand,
                        service_type=service_type,
                        profile=profile,
                        expiry_date=expiry_date
                    )
                    db.session.add(sub)
                    db.session.commit()
                    
                    # إرسال كل كارت من الكروت المنشأة تلقائياً للسيرفر الأول
                    sync_userman(uname, p_rand, action='add')
                except Exception:
                    db.session.rollback()

        return redirect(url_for('subscribers'))

    return render_template('add_subscriber.html')

@app.route('/edit_subscriber/<int:id>', methods=['GET', 'POST'])
def edit_subscriber(id):
    sub = Subscriber.query.get_or_404(id)
    if request.method == 'POST':
        try:
            old_username = sub.username
            sub.username = request.form.get('username')
            sub.password = request.form.get('password')
            sub.service_type = request.form.get('service_type', 'PPPoE')
            sub.profile = request.form.get('profile')
            sub.phone = request.form.get('phone')
            sub.expiry_date = request.form.get('expiry_date')
            sub.status = request.form.get('status', 'active')
            db.session.commit()

            # التحديث في User Manager عبر حذف القديم وإضافة الجديد
            sync_userman(old_username, sub.password, action='delete')
            sync_userman(sub.username, sub.password, action='add')
        except Exception:
            db.session.rollback()
        return redirect(url_for('subscribers'))
    return render_template('edit_subscriber.html', subscriber=sub)

@app.route('/delete_subscriber/<int:id>')
def delete_subscriber(id):
    try:
        sub = Subscriber.query.get_or_404(id)
        # حذف الحساب فورياً من User Manager بالسيرفر الرئيسي
        sync_userman(sub.username, sub.password, action='delete')

        db.session.delete(sub)
        db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('subscribers'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
