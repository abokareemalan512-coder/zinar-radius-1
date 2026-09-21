import os
import random
import string
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy

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
        'packages': 'الباقات',
        'login': 'تسجيل الدخول'
    }
    return translations.get(key, key)

app.jinja_env.globals['t'] = t

class Router(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(50), nullable=False)
    username = db.Column(db.String(50), nullable=False)
    password = db.Column(db.String(50), nullable=False)

class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    service_type = db.Column(db.String(20), default='PPPoE')
    profile = db.Column(db.String(50), nullable=False, default='Default')
    phone = db.Column(db.String(30), nullable=True)
    expiry_date = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), default='active')

with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"Database creation error: {e}")

def generate_random_str(length=6):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    routers_count = 0
    sub_count = 0
    active_subs = 0
    subscribers = []
    
    try:
        routers_count = Router.query.count()
        sub_count = Subscriber.query.count()
        active_subs = Subscriber.query.filter_by(status='active').count()
        subscribers = Subscriber.query.all()
    except Exception as e:
        print(f"Dashboard query error: {e}")

    return render_template(
        'dashboard.html',
        routers_count=routers_count,
        sub_count=sub_count,
        active_subs=active_subs,
        subscribers=subscribers
    )

@app.route('/routers', methods=['GET', 'POST'])
def routers():
    if request.method == 'POST':
        name = request.form.get('name')
        ip_address = request.form.get('ip_address')
        username = request.form.get('username')
        password = request.form.get('password')
        if name and ip_address:
            try:
                new_router = Router(name=name, ip_address=ip_address, username=username, password=password)
                db.session.add(new_router)
                db.session.commit()
            except Exception:
                db.session.rollback()
        return redirect(url_for('routers'))
    
    routers_list = []
    try:
        routers_list = Router.query.all()
    except Exception:
        pass
    return render_template('routers.html', routers=routers_list)

@app.route('/subscribers')
def subscribers():
    subscribers_list = []
    try:
        subscribers_list = Subscriber.query.all()
    except Exception:
        pass
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
                except Exception:
                    db.session.rollback()

        elif mode == 'bulk':
            count = int(request.form.get('count', 10))
            prefix = request.form.get('prefix', '')
            pass_len = int(request.form.get('password_length', 6))

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
                except Exception:
                    pass
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

        return redirect(url_for('subscribers'))

    return render_template('add_subscriber.html')

@app.route('/edit_subscriber/<int:id>', methods=['GET', 'POST'])
def edit_subscriber(id):
    sub = Subscriber.query.get_or_404(id)
    if request.method == 'POST':
        try:
            sub.username = request.form.get('username')
            sub.password = request.form.get('password')
            sub.service_type = request.form.get('service_type', 'PPPoE')
            sub.profile = request.form.get('profile')
            sub.phone = request.form.get('phone')
            sub.expiry_date = request.form.get('expiry_date')
            sub.status = request.form.get('status', 'active')
            db.session.commit()
        except Exception:
            db.session.rollback()
        return redirect(url_for('subscribers'))
    return render_template('edit_subscriber.html', subscriber=sub)

@app.route('/delete_subscriber/<int:id>')
def delete_subscriber(id):
    try:
        sub = Subscriber.query.get_or_404(id)
        db.session.delete(sub)
        db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('subscribers'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
