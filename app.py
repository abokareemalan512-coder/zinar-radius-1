import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'zinar-secret-key-123')

# إعداد قاعدة البيانات
database_url = os.environ.get('DATABASE_URL', 'sqlite:///zinar.db')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ----------------- نماذج قاعدة البيانات -----------------
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
    profile = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    expiry_date = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), default='active')

# إنشاء الجداول عند البدء
with app.app_context():
    db.create_all()

# ----------------- معالج الترجمة المدمج للقوالب -----------------
@app.context_processor
def utility_processor():
    def t(key):
        translations = {
            'brand_sub': 'نظام إدارة المشتركين',
            'dashboard': 'لوحة التحكم',
            'routers': 'الراوترات',
            'subscribers': 'المشتركين',
            'add_subscriber': 'إضافة مشترك',
            'packages': 'الباقات'
        }
        return translations.get(key, key)
    return dict(t=t)

# ----------------- المسارات -----------------
@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    try:
        routers_count = Router.query.count()
        sub_count = Subscriber.query.count()
        active_subs = Subscriber.query.filter_by(status='active').count()
        subscribers = Subscriber.query.all()
    except Exception:
        routers_count = 0
        sub_count = 0
        active_subs = 0
        subscribers = []

    return render_template(
        'dashboard.html',
        routers_count=routers_count,
        sub_count=sub_count,
        active_subs=active_subs,
        subscribers=subscribers,
        active_sessions=0,
        today_revenue=0,
        active_vouchers=0
    )

@app.route('/routers', methods=['GET', 'POST'])
def routers():
    if request.method == 'POST':
        name = request.form.get('name')
        ip_address = request.form.get('ip_address')
        username = request.form.get('username')
        password = request.form.get('password')
        if name and ip_address:
            new_router = Router(name=name, ip_address=ip_address, username=username, password=password)
            db.session.add(new_router)
            db.session.commit()
        return redirect(url_for('routers'))
    
    try:
        routers_list = Router.query.all()
    except Exception:
        routers_list = []
    return render_template('routers.html', routers=routers_list)

@app.route('/subscribers')
def subscribers():
    try:
        subscribers_list = Subscriber.query.all()
    except Exception:
        subscribers_list = []
    return render_template('subscribers.html', subscribers=subscribers_list)

@app.route('/add_subscriber', methods=['GET', 'POST'])
def add_subscriber():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        profile = request.form.get('profile', 'Default')
        phone = request.form.get('phone', '')
        expiry_date = request.form.get('expiry_date', '')
        if username and password:
            sub = Subscriber(username=username, password=password, profile=profile, phone=phone, expiry_date=expiry_date)
            db.session.add(sub)
            db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template('add_subscriber.html')

@app.route('/delete_subscriber/<int:id>')
def delete_subscriber(id):
    sub = Subscriber.query.get_or_404(id)
    db.session.delete(sub)
    db.session.commit()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
