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

# --- نماذج قاعدة البيانات ---

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

class Package(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    download_speed = db.Column(db.String(20), nullable=False, default='1M')
    upload_speed = db.Column(db.String(20), nullable=False, default='1M')
    price = db.Column(db.Float, nullable=False, default=0.0)
    validity_days = db.Column(db.Integer, nullable=False, default=30)

class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    service_type = db.Column(db.String(20), default='Hotspot')
    profile = db.Column(db.String(100), nullable=False, default='1M')
    phone = db.Column(db.String(30), nullable=True)
    expiry_date = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), default='active')

with app.app_context():
    try:
        db.create_all()
        admin_account = Admin.query.first()
        if not admin_account:
            default_admin = Admin(username='admin', password='admin')
            db.session.add(default_admin)
            db.session.commit()
    except Exception as e:
        print(f"Database init note: {e}")

def generate_random_str(length=6):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def sync_userman(username, password, profile_name="1M", action='add'):
    try:
        main_router = Router.query.first()
        router_ip = main_router.ip_address if main_router else "198.145.118.146"
        api_user = main_router.username if main_router else "admin"
        api_pass = main_router.password if (main_router and main_router.password) else ""
        api_port = main_router.port if main_router else 8728

        connection = routeros_api.RouterOsApiPool(
            router_ip,
            username=api_user,
            password=api_pass,
            port=api_port,
            plaintext_login=True
        )
        api = connection.get_api()
        userman_users = api.get_resource('/tool/user-manager/user')

        if action in ['add', 'update']:
            existing = userman_users.get(username=username)
            if not existing:
                userman_users.add(customer='admin', username=username, password=password)
            else:
                user_id = existing[0]['.id']
                userman_users.set(id=user_id, password=password)

            try:
                userman_users.call('create-and-activate-profile', {
                    'customer': 'admin',
                    'numbers': username,
                    'profile': profile_name
                })
            except Exception as pe:
                print(f"Profile Activation Note: {pe}")

        elif action == 'delete':
            existing = userman_users.get(username=username)
            if existing:
                userman_users.remove(id=existing[0]['.id'])

        connection.disconnect()
        return True
    except Exception as e:
        print(f"User Manager API Error: {e}")
        return False

# --- المسارات ---

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    routers_count = Router.query.count()
    packages_count = Package.query.count()
    sub_count = Subscriber.query.count()
    active_subs = Subscriber.query.filter_by(status='active').count()
    subscribers = Subscriber.query.order_by(Subscriber.id.desc()).limit(10).all()

    return render_template(
        'dashboard.html',
        routers_count=routers_count,
        packages_count=packages_count,
        sub_count=sub_count,
        active_subs=active_subs,
        subscribers=subscribers
    )

@app.route('/packages', methods=['GET', 'POST'])
def packages():
    if request.method == 'POST':
        name = request.form.get('name')
        download_speed = request.form.get('download_speed', '1M')
        upload_speed = request.form.get('upload_speed', '1M')
        price = float(request.form.get('price', 0.0) or 0.0)
        validity_days = int(request.form.get('validity_days', 30) or 30)

        if name:
            try:
                new_pkg = Package(
                    name=name,
                    download_speed=download_speed,
                    upload_speed=upload_speed,
                    price=price,
                    validity_days=validity_days
                )
                db.session.add(new_pkg)
                db.session.commit()
            except Exception:
                db.session.rollback()
        return redirect(url_for('packages'))

    all_packages = Package.query.order_by(Package.id.desc()).all()
    return render_template('packages.html', packages=all_packages)

@app.route('/delete_package/<int:id>')
def delete_package(id):
    try:
        pkg = Package.query.get_or_404(id)
        db.session.delete(pkg)
        db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('packages'))

@app.route('/subscribers')
def subscribers():
    search_query = request.args.get('search', '')
    if search_query:
        subscribers_list = Subscriber.query.filter(Subscriber.username.contains(search_query)).order_by(Subscriber.id.desc()).all()
    else:
        subscribers_list = Subscriber.query.order_by(Subscriber.id.desc()).all()
    return render_template('subscribers.html', subscribers=subscribers_list)

@app.route('/add_subscriber', methods=['GET', 'POST'])
def add_subscriber():
    packages_list = Package.query.all()
    if request.method == 'POST':
        mode = request.form.get('mode', 'single')
        service_type = request.form.get('service_type', 'Hotspot')
        package_name = request.form.get('package_name', '1M')
        
        selected_pkg = Package.query.filter_by(name=package_name).first()
        valid_days = selected_pkg.validity_days if selected_pkg else 30
        expiry_date = (datetime.now() + timedelta(days=valid_days)).strftime('%Y-%m-%d')

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
                        profile=package_name,
                        phone=phone,
                        expiry_date=expiry_date
                    )
                    db.session.add(sub)
                    db.session.commit()
                    sync_userman(username, password, profile_name=package_name, action='add')
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
                        profile=package_name,
                        expiry_date=expiry_date
                    )
                    db.session.add(sub)
                    db.session.commit()
                    sync_userman(uname, p_rand, profile_name=package_name, action='add')
                except Exception:
                    db.session.rollback()

        return redirect(url_for('subscribers'))

    return render_template('add_subscriber.html', packages=packages_list)

@app.route('/delete_subscriber/<int:id>')
def delete_subscriber(id):
    try:
        sub = Subscriber.query.get_or_404(id)
        sync_userman(sub.username, sub.password, action='delete')
        db.session.delete(sub)
        db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('subscribers'))

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
            except Exception:
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

if __name__ == '__main__':
    port = int(os.environ.get('ZINAR_PORT', 1892))
    app.run(debug=False, host='0.0.0.0', port=port)
