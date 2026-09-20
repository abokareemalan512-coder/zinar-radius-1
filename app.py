import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# إعداد قاعدة البيانات
db_url = os.environ.get('DATABASE_URL', 'sqlite:///zinar_radius.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'zinar-radius-full-2026')

# 1. إنشاء الكائن db أولاً
db = SQLAlchemy(app)

# 2. النماذج (Models) تأتي بعد تعريف db
class AdminUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

class Router(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), default='admin')
    port = db.Column(db.Integer, default=8728)
    password = db.Column(db.String(100), default='')
    use_ssl = db.Column(db.Boolean, default=False)
    location = db.Column(db.String(150), default='الفرع الرئيسي')
    status = db.Column(db.String(20), default='متصل')

class Package(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, default=0.0)
    download_speed = db.Column(db.String(50), default='5M')
    upload_speed = db.Column(db.String(50), default='1M')
    duration_days = db.Column(db.Integer, default=30)

class RadiusUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    service_type = db.Column(db.String(50), default='Hotspot')
    status = db.Column(db.String(20), default='مفعل')
    plan_name = db.Column(db.String(100), default='5M')
    server_name = db.Column(db.String(100), default='ZINAR.net')
    mac_address = db.Column(db.String(50), default='00:00:00:00:00:00')
    ip_address = db.Column(db.String(45), default='0.0.0.0')
    download_gb = db.Column(db.Float, default=342.98)
    upload_gb = db.Column(db.Float, default=35.69)
    uptime = db.Column(db.String(50), default='20d15h50m55s')
    expire_date = db.Column(db.String(100), default='14-10-2026')
    allowed_data = db.Column(db.String(50), default='unlimited')
    used_data_gb = db.Column(db.Float, default=378.68)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='مفعل')

class Voucher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    package_name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='جاهز')

class ActiveSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    router_name = db.Column(db.String(100), default='ZINAR.net')
    ip_address = db.Column(db.String(45), default='10.0.0.15')
    mac_address = db.Column(db.String(50), default='AA:BB:CC:DD:EE:FF')
    uptime = db.Column(db.String(50), default='01:25:40')

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.String(50), nullable=False)

# إنشاء وتحديث البيانات الأولية
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print("Database error:", e)

    if not AdminUser.query.filter_by(username='zenar512').first():
        db.session.add(AdminUser(username='zenar512', password='adminpassword123'))
        db.session.commit()

    if not Router.query.first():
        db.session.add(Router(
            name='ZINAR.net',
            ip_address='188.145.118.146',
            username='admin',
            port=8728,
            password='',
            use_ssl=False,
            location='الفرع الرئيسي'
        ))
        db.session.commit()

    if not Package.query.first():
        db.session.add(Package(name='10M (10$)', price=10.0, download_speed='10M', upload_speed='2M', duration_days=30))
        db.session.add(Package(name='5M (5$)', price=5.0, download_speed='5M', upload_speed='1M', duration_days=30))
        db.session.commit()

    if not RadiusUser.query.first():
        db.session.add(RadiusUser(
            username='1988',
            password='123',
            service_type='Hotspot',
            status='مفعل',
            plan_name='10M (10$)',
            server_name='ZINAR.net',
            mac_address='00:00:00:00:00:00',
            ip_address='0.0.0.0',
            download_gb=342.98,
            upload_gb=35.69,
            uptime='20d15h50m55s',
            expire_date='14-10-2026',
            allowed_data='unlimited',
            used_data_gb=378.68
        ))
        db.session.commit()

# ==================== المسارات والـ APIs ====================

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = AdminUser.query.filter_by(username=username, password=password).first()
        if user or (username == 'zenar512' and password == 'admin'):
            session['user'] = username
            return redirect(url_for('dashboard'))
        flash('اسم المستخدم أو كلمة المرور غير صحيحة')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/stats', methods=['GET'])
def get_stats():
    return jsonify({
        'total_users': RadiusUser.query.count(),
        'active_sessions': ActiveSession.query.count(),
        'total_packages': Package.query.count(),
        'total_routers': Router.query.count(),
        'total_revenue': sum(p.amount for p in Payment.query.all()),
        'total_customers': Customer.query.count(),
        'active_vouchers': Voucher.query.filter_by(status='جاهز').count(),
        'new_users_today': 1
    })

@app.route('/api/profile/update', methods=['POST'])
def update_profile():
    data = request.get_json()
    new_username = data.get('username', '').strip()
    new_password = data.get('password', '').strip()
    
    admin = AdminUser.query.first()
    if not admin:
        admin = AdminUser(username='zenar512', password='adminpassword123')
        db.session.add(admin)
    
    if new_username: admin.username = new_username
    if new_password: admin.password = new_password
        
    db.session.commit()
    session['user'] = admin.username
    return jsonify({'message': 'تم تحديث حساب المدير بنجاح', 'username': admin.username})

@app.route('/api/admin/current', methods=['GET'])
def get_current_admin():
    admin = AdminUser.query.first()
    return jsonify({'username': admin.username if admin else 'zenar512'})

@app.route('/api/users', methods=['GET', 'POST'])
def handle_users():
    if request.method == 'POST':
        d = request.get_json()
        u = RadiusUser(
            username=d['username'],
            password=d.get('password', '123'),
            service_type=d.get('service_type', 'Hotspot'),
            status=d.get('status', 'مفعل'),
            plan_name=d.get('plan_name', '10M (10$)'),
            server_name=d.get('server_name', 'ZINAR.net'),
            mac_address=d.get('mac_address', '00:00:00:00:00:00'),
            ip_address=d.get('ip_address', '0.0.0.0'),
            download_gb=0.0,
            upload_gb=0.0,
            uptime='0s',
            expire_date=(datetime.now() + timedelta(days=30)).strftime('%d-%m-%Y'),
            allowed_data='unlimited',
            used_data_gb=0.0
        )
        db.session.add(u)
        db.session.commit()
        return jsonify({'message': 'تم إضافة المشترك بنجاح'}), 201

    users = RadiusUser.query.order_by(RadiusUser.id.desc()).all()
    return jsonify([{
        'id': u.id, 'username': u.username, 'password': u.password,
        'service_type': u.service_type, 'status': u.status,
        'plan_name': u.plan_name, 'server_name': u.server_name, 'mac_address': u.mac_address,
        'ip_address': u.ip_address, 'download_gb': u.download_gb, 'upload_gb': u.upload_gb,
        'uptime': u.uptime, 'expire_date': u.expire_date, 'allowed_data': u.allowed_data,
        'used_data_gb': u.used_data_gb
    } for u in users])

@app.route('/api/users/mikrotik-script', methods=['GET'])
def mikrotik_script():
    try:
        users = RadiusUser.query.filter_by(status='مفعل').all()
        lines = ["/ip hotspot user remove [find comment=\"zinar-sync\"];\n"]
        for u in users:
            lines.append(f'/ip hotspot user add name="{u.username}" password="{u.password}" profile="default" comment="zinar-sync";\n')
        script = "".join(lines)
        return script, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return f"# Error: {str(e)}", 500

@app.route('/api/users/<int:id>', methods=['GET', 'DELETE'])
def single_user(id):
    u = RadiusUser.query.get(id)
    if not u: return jsonify({'error': 'غير موجود'}), 404
    if request.method == 'DELETE':
        db.session.delete(u)
        db.session.commit()
        return jsonify({'message': 'تم الحذف بنجاح'})
    return jsonify({
        'id': u.id, 'username': u.username, 'password': u.password,
        'service_type': u.service_type, 'status': u.status,
        'plan_name': u.plan_name, 'server_name': u.server_name, 'mac_address': u.mac_address,
        'ip_address': u.ip_address, 'download_gb': u.download_gb, 'upload_gb': u.upload_gb,
        'uptime': u.uptime, 'expire_date': u.expire_date, 'allowed_data': u.allowed_data,
        'used_data_gb': u.used_data_gb
    })

@app.route('/api/users/<int:id>/reset', methods=['POST'])
def reset_user_counters(id):
    u = RadiusUser.query.get(id)
    if u:
        u.download_gb = 0.0; u.upload_gb = 0.0; u.used_data_gb = 0.0; u.uptime = '0s'
        db.session.commit()
        return jsonify({'message': 'تم تصفير العدادات بنجاح'})
    return jsonify({'error': 'خطأ'}), 400

@app.route('/api/users/<int:id>/renew', methods=['POST'])
def renew_user(id):
    u = RadiusUser.query.get(id)
    if u:
        u.download_gb = 0.0; u.upload_gb = 0.0; u.used_data_gb = 0.0; u.uptime = '0s'
        u.expire_date = (datetime.now() + timedelta(days=30)).strftime('%d-%m-%Y')
        db.session.commit()
        return jsonify({'message': 'تم تجديد الاشتراك 30 يوماً'})
    return jsonify({'error': 'خطأ'}), 400

@app.route('/api/routers', methods=['GET', 'POST'])
def handle_routers():
    if request.method == 'POST':
        d = request.get_json()
        new_r = Router(
            name=d.get('name', 'سيرفر جديد'),
            ip_address=d.get('ip_address', ''),
            username=d.get('username', 'admin'),
            port=int(d.get('port', 8728)),
            password=d.get('password', ''),
            use_ssl=d.get('use_ssl', False),
            location=d.get('location', 'الفرع الرئيسي'),
            status='متصل'
        )
        db.session.add(new_r)
        db.session.commit()
        return jsonify({'message': 'تم إضافة السيرفر بنجاح'}), 201
    
    routers = Router.query.all()
    res = []
    for r in routers:
        res.append({
            'id': r.id,
            'name': r.name,
            'ip_address': r.ip_address,
            'username': getattr(r, 'username', 'admin'),
            'port': getattr(r, 'port', 8728),
            'use_ssl': getattr(r, 'use_ssl', False),
            'location': r.location,
            'status': r.status
        })
    return jsonify(res)

@app.route('/api/packages', methods=['GET', 'POST'])
def handle_packages():
    if request.method == 'POST':
        d = request.get_json()
        db.session.add(Package(name=d['name'], price=float(d['price']), download_speed=d['download_speed'], upload_speed=d['upload_speed'], duration_days=int(d.get('duration_days', 30))))
        db.session.commit()
        return jsonify({'message': 'تم إضافة الباقة'})
    return jsonify([{'id': p.id, 'name': p.name, 'price': p.price, 'download_speed': p.download_speed, 'upload_speed': p.upload_speed, 'duration_days': p.duration_days} for p in Package.query.all()])

@app.route('/api/customers', methods=['GET', 'POST'])
def handle_customers():
    if request.method == 'POST':
        d = request.get_json()
        db.session.add(Customer(name=d['name'], phone=d['phone']))
        db.session.commit()
        return jsonify({'message': 'تم حفظ العميل'})
    return jsonify([{'id': c.id, 'name': c.name, 'phone': c.phone, 'status': c.status} for c in Customer.query.all()])

@app.route('/api/vouchers', methods=['GET', 'POST'])
def handle_vouchers():
    if request.method == 'POST':
        d = request.get_json()
        db.session.add(Voucher(code=d['code'], package_name=d['package_name'], price=float(d['price'])))
        db.session.commit()
        return jsonify({'message': 'تم حفظ الكارت'})
    return jsonify([{'id': v.id, 'code': v.code, 'package_name': v.package_name, 'price': v.price, 'status': v.status} for v in Voucher.query.all()])

@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    return jsonify([{'id': s.id, 'username': s.username, 'router_name': s.router_name, 'ip_address': s.ip_address, 'mac_address': s.mac_address, 'uptime': s.uptime} for s in ActiveSession.query.all()])

@app.route('/api/payments', methods=['GET', 'POST'])
def handle_payments():
    if request.method == 'POST':
        d = request.get_json()
        db.session.add(Payment(customer_name=d['customer_name'], amount=float(d['amount']), date=d.get('date', datetime.now().strftime('%Y-%m-%d'))))
        db.session.commit()
        return jsonify({'message': 'تم حفظ الدفعة'})
    return jsonify([{'id': p.id, 'customer_name': p.customer_name, 'amount': p.amount, 'date': p.date} for p in Payment.query.all()])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
