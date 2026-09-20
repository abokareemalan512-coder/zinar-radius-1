from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from mikrotik_api import MikroTikAPI

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///zinar_radius.db'
app.config['SECRET_KEY'] = 'zinar_secret_key_2026'
db = SQLAlchemy(app)

class Router(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    ip = db.Column(db.String(100), nullable=False)
    port = db.Column(db.Integer, default=8728)
    username = db.Column(db.String(50), default='admin')
    password = db.Column(db.String(100), default='')

class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    router_id = db.Column(db.Integer, db.ForeignKey('router.id'), nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    profile = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(50))
    status = db.Column(db.String(20), default='active')
    expiry_date = db.Column(db.String(50))
    router = db.relationship('Router', backref=db.backref('subscribers', lazy=True))

with app.app_context():
    db.create_all()

@app.route('/')
def dashboard():
    routers_count = Router.query.count()
    sub_count = Subscriber.query.count()
    active_subs = Subscriber.query.filter_by(status='active').count()
    subscribers = Subscriber.query.all()
    return render_template('dashboard.html', routers_count=routers_count, sub_count=sub_count, active_subs=active_subs, subscribers=subscribers)

@app.route('/routers')
def routers():
    all_routers = Router.query.all()
    return render_template('routers.html', routers=all_routers)

@app.route('/routers/add', methods=['GET', 'POST'])
def add_router():
    if request.method == 'POST':
        new_router = Router(
            name=request.form['name'],
            ip=request.form['ip'],
            port=request.form.get('port', 8728),
            username=request.form['username'],
            password=request.form['password']
        )
        db.session.add(new_router)
        db.session.commit()
        flash('تم إضافة السيرفر بنجاح', 'success')
        return redirect(url_for('routers'))
    return render_template('add_router.html')

@app.route('/subscribers/add', methods=['GET', 'POST'])
def add_subscriber():
    routers = Router.query.all()
    if request.method == 'POST':
        router_id = request.form['router_id']
        username = request.form['username']
        password = request.form['password']
        profile = request.form['profile']
        phone = request.form.get('phone', '')
        expiry_date = request.form['expiry_date']

        router = Router.query.get(router_id)
        if router:
            mt = MikroTikAPI(router.ip, router.port, router.username, router.password)
            mt.add_pppoe_user(username, password, profile)

        new_sub = Subscriber(
            router_id=router_id,
            username=username,
            password=password,
            profile=profile,
            phone=phone,
            expiry_date=expiry_date,
            status='active'
        )
        db.session.add(new_sub)
        db.session.commit()
        flash('تم إضافة المشترك بنجاح وتفعيله على الميكروتيك', 'success')
        return redirect(url_for('dashboard'))
    return render_template('add_subscriber.html', routers=routers)

@app.route('/subscribers/edit/<int:id>', methods=['GET', 'POST'])
def edit_subscriber(id):
    sub = Subscriber.query.get_or_404(id)
    routers = Router.query.all()
    if request.method == 'POST':
        sub.username = request.form['username']
        sub.password = request.form['password']
        sub.profile = request.form['profile']
        sub.phone = request.form['phone']
        sub.expiry_date = request.form['expiry_date']
        sub.status = request.form['status']
        db.session.commit()
        flash('تم تحديث بيانات المشترك بنجاح', 'success')
        return redirect(url_for('dashboard'))
    return render_template('edit_subscriber.html', sub=sub, routers=routers)

@app.route('/subscribers/delete/<int:id>')
def delete_subscriber(id):
    sub = Subscriber.query.get_or_404(id)
    if sub.router:
        mt = MikroTikAPI(sub.router.ip, sub.router.port, sub.router.username, sub.router.password)
        mt.remove_pppoe_user(sub.username)
    
    db.session.delete(sub)
    db.session.commit()
    flash('تم حذف المشترك من المنصة والسيرفر بنجاح', 'danger')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
