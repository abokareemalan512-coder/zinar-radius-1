import os
import socket
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'zinar_secret_key_2026')

db_url = os.environ.get('DATABASE_URL', 'sqlite:///zinar.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==================== النماذج (Models) ====================

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, default='zinar')
    password = db.Column(db.String(200), nullable=False, default='admin123')

class Router(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(50), nullable=False)
    port = db.Column(db.Integer, default=8728)
    username = db.Column(db.String(50), default='admin')
    password = db.Column(db.String(100), nullable=False)
    is_master = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=False)

class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(50))
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    amount_paid = db.Column(db.Float, default=0.0)

class EventLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_name = db.Column(db.String(80), default='zinar')
    action = db.Column(db.String(100))
    target = db.Column(db.String(100))
    details = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def check_router_status(ip, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5) # وقت انتظار قصير جداً لمنع تعليق الخادم
        result = sock.connect_ex((str(ip), int(port)))
        sock.close()
        return result == 0
    except Exception:
        return False

# ==================== المسارات (Routes) ====================

@app.route('/')
@app.route('/dashboard')
def dashboard():
    admin_name = session.get('admin_name', 'zinar')
    routers = []
    try:
        routers = Router.query.all()
    except Exception:
        routers = []

    routers_count = len(routers)
    routers_online = 0
    for r in routers:
        try:
            if check_router_status(r.ip_address, r.port):
                r.is_active = True
                routers_online += 1
            else:
                r.is_active = False
        except Exception:
            r.is_active = False

    has_master = any(r.is_master for r in routers)
    
    try:
        sub_count = Subscriber.query.count()
        active_subs = Subscriber.query.filter_by(status='active').count()
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_revenue = db.session.query(db.func.sum(Subscriber.amount_paid)).filter(Subscriber.created_at >= today_start).scalar() or 0
        new_users_today = Subscriber.query.filter(Subscriber.created_at >= today_start).count()
        events = EventLog.query.order_by(EventLog.created_at.desc()).limit(20).all()
    except Exception:
        sub_count = 0
        active_subs = 0
        today_revenue = 0
        new_users_today = 0
        events = []

    return render_template('dashboard.html',
                           routers=routers,
                           routers_count=routers_count,
                           routers_online=routers_online,
                           has_master=has_master,
                           sub_count=sub_count,
                           active_subs=active_subs,
                           today_revenue=today_revenue,
                           new_users_today=new_users_today,
                           events=events,
                           admin_name=admin_name)

@app.route('/routers', methods=['GET', 'POST'])
def routers():
    if request.method == 'POST':
        name = request.form.get('name')
        ip_address = request.form.get('ip_address')
        username = request.form.get('username', 'admin')
        password = request.form.get('password')
        port = int(request.form.get('port', 8728))
        is_master = True if request.form.get('is_master') else False

        if is_master:
            try:
                Router.query.update({Router.is_master: False})
            except:
                pass

        is_active = check_router_status(ip_address, port)
        try:
            new_router = Router(
                name=name,
                ip_address=ip_address,
                username=username,
                password=password,
                port=port,
                is_master=is_master,
                is_active=is_active
            )
            db.session.add(new_router)
            db.session.commit()
            flash('تم إضافة السيرفر بنجاح', 'success')
        except Exception:
            db.session.rollback()
            flash('حدث خطأ أثناء حفظ السيرفر', 'danger')
        return redirect(url_for('routers'))

    try:
        all_routers = Router.query.all()
        for r in all_routers:
            r.is_active = check_router_status(r.ip_address, r.port)
    except Exception:
        all_routers = []

    return render_template('routers.html', routers=all_routers)

@app.route('/routers/update/<int:router_id>', methods=['POST'])
def update_router(router_id):
    try:
        router = Router.query.get_or_404(router_id)
        router.name = request.form.get('name')
        router.ip_address = request.form.get('ip_address')
        router.username = request.form.get('username')
        router.port = int(request.form.get('port', 8728))
        
        new_pass = request.form.get('password')
        if new_pass:
            router.password = new_pass

        router.is_active = check_router_status(router.ip_address, router.port)
        db.session.commit()
        flash('تم تحديث بيانات السيرفر بنجاح', 'success')
    except Exception:
        db.session.rollback()
        flash('حدث خطأ أثناء التحديث', 'danger')
    return redirect(url_for('routers'))

@app.route('/routers/toggle/<int:router_id>')
def toggle_router(router_id):
    try:
        router = Router.query.get_or_404(router_id)
        router.is_active = not router.is_active
        db.session.commit()
    except:
        pass
    return redirect(url_for('routers'))

@app.route('/routers/test/<int:router_id>')
def test_router(router_id):
    try:
        router = Router.query.get_or_404(router_id)
        router.is_active = check_router_status(router.ip_address, router.port)
        db.session.commit()
        if router.is_active:
            flash(f'الاتصال بالسيرفر {router.name} ناجح (متصل 🟢)', 'success')
        else:
            flash(f'تعذر الاتصال بالسيرفر {router.name} عبر الـ IP {router.ip_address} (غير متصل 🔴)', 'danger')
    except:
        flash('حدث خطأ أثناء اختبار الاتصال', 'danger')
    return redirect(url_for('routers'))

@app.route('/routers/master/<int:router_id>')
def set_master_router(router_id):
    try:
        Router.query.update({Router.is_master: False})
        router = Router.query.get_or_404(router_id)
        router.is_master = True
        db.session.commit()
        flash(f'تم تعيين {router.name} كـ سيرفر رئيسي', 'success')
    except:
        pass
    return redirect(url_for('routers'))

@app.route('/routers/delete/<int:router_id>')
def delete_router(router_id):
    try:
        router = Router.query.get_or_404(router_id)
        db.session.delete(router)
        db.session.commit()
        flash('تم حذف السيرفر', 'info')
    except:
        pass
    return redirect(url_for('routers'))

@app.route('/router_users/<int:router_id>')
def router_users(router_id):
    router = Router.query.get_or_404(router_id)
    return render_template('router_users.html', router=router, users=[])

@app.route('/import_rsc/<int:router_id>')
def import_rsc(router_id):
    router = Router.query.get_or_404(router_id)
    flash(f'استيراد ملف .rsc للسيرفر {router.name}', 'info')
    return redirect(url_for('routers'))

@app.route('/subscribers')
def subscribers():
    try:
        subs = Subscriber.query.all()
    except:
        subs = []
    return render_template('subscribers.html', subscribers=subs)

@app.route('/add_subscriber', methods=['GET', 'POST'])
def add_subscriber():
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            phone = request.form.get('phone')
            amount = float(request.form.get('amount', 0))
            sub = Subscriber(name=name, phone=phone, amount_paid=amount, status='active')
            db.session.add(sub)
            db.session.commit()
            flash('تم إضافة المشترك بنجاح', 'success')
        except:
            db.session.rollback()
            flash('حدث خطأ', 'danger')
        return redirect(url_for('subscribers'))
    return render_template('add_subscriber.html')

@app.route('/payments')
def payments():
    try:
        subs = Subscriber.query.all()
    except:
        subs = []
    return render_template('payments.html', payments=subs)

@app.route('/change_credentials', methods=['POST'])
def change_admin_credentials():
    try:
        current_pass = request.form.get('current_password')
        new_user = request.form.get('new_username')
        new_pass = request.form.get('new_password')
        
        admin = Admin.query.first()
        if not admin:
            admin = Admin(username='zinar', password='admin123')
            db.session.add(admin)
            db.session.commit()
            
        if current_pass == admin.password:
            if new_user:
                admin.username = new_user
                session['admin_name'] = new_user
            if new_pass:
                admin.password = new_pass
            db.session.commit()
            flash('تم تغيير بيانات الدخول بنجاح', 'success')
        else:
            flash('كلمة المرور الحالية غير صحيحة', 'danger')
    except:
        flash('حدث خطأ', 'danger')
    return redirect(url_for('dashboard'))

with app.app_context():
    db.create_all()
    try:
        if not Admin.query.first():
            default_admin = Admin(username='zinar', password='admin123')
            db.session.add(default_admin)
            db.session.commit()
    except:
        pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
