import sqlite3, traceback
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, g
import routeros_api

try:
    from config import SHAM_CASH_ACCOUNT, SHAM_CASH_ENABLED, PACKAGES_PRICES
except:
    SHAM_CASH_ACCOUNT="5889"; SHAM_CASH_ENABLED=True
    PACKAGES_PRICES={"1M":4,"2M":5,"4M":7,"8M":10}

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
    if db is not None: db.close()

def init_db():
    with app.app_context():
        db = get_db(); c=db.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS routers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, ip_address TEXT, username TEXT, password TEXT, port INTEGER DEFAULT 8728, status TEXT DEFAULT 'disconnected')''')
        c.execute('''CREATE TABLE IF NOT EXISTS subscribers (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, profile TEXT, service_type TEXT DEFAULT 'hotspot', phone TEXT DEFAULT '', full_name TEXT DEFAULT '', status TEXT DEFAULT 'active', start_date TEXT, expiry_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS packages (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rate_limit TEXT, price REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, subscriber_username TEXT, package_name TEXT, amount REAL, shamcash_tx TEXT, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        db.commit()
        # ترقية الجدول القديم
        try:
            for col in ['phone','full_name','start_date','expiry_date']:
                try: c.execute(f'ALTER TABLE subscribers ADD COLUMN {col} TEXT DEFAULT ""')
                except: pass
            db.commit()
        except: pass
        count=c.execute('SELECT COUNT(*) FROM packages').fetchone()[0]
        if count==0:
            for n,p in PACKAGES_PRICES.items():
                try: c.execute('INSERT INTO packages (name,rate_limit,price) VALUES (?,?,?)',(n,f"{n}/{n}",p))
                except: pass
            db.commit()
init_db()

def connect_mikrotik(ip,user,pwd,port=8728):
    try:
        ip=str(ip).replace('http://','').replace('https://','').strip()
        pool=routeros_api.RouterOsApiPool(ip,username=str(user).strip(),password=str(pwd).strip(),port=int(port),plaintext_login=True)
        return pool.get_api(),pool,None
    except Exception as e: return None,None,str(e)

@app.route('/')
@app.route('/dashboard')
def dashboard():
    db=get_db(); cur=db.cursor()
    rc=cur.execute('SELECT COUNT(*) FROM routers').fetchone()[0]
    pc=cur.execute('SELECT COUNT(*) FROM packages').fetchone()[0]
    sc=cur.execute('SELECT COUNT(*) FROM subscribers').fetchone()[0]
    ac=cur.execute("SELECT COUNT(*) FROM subscribers WHERE status='active'").fetchone()[0]
    subs=cur.execute('SELECT * FROM subscribers ORDER BY id DESC LIMIT 10').fetchall()
    return render_template('dashboard.html',routers_count=rc,packages_count=pc,sub_count=sc,active_subs=ac,subscribers=subs,sham_account=SHAM_CASH_ACCOUNT)

@app.route('/routers',methods=['GET','POST'])
def routers():
    db=get_db(); cur=db.cursor()
    if request.method=='POST':
        cur.execute('INSERT INTO routers (name,ip_address,username,password,port) VALUES (?,?,?,?,?)',(request.form.get('name'),request.form.get('ip_address'),request.form.get('username'),request.form.get('password'),request.form.get('port',8728)))
        db.commit(); return redirect(url_for('routers'))
    return render_template('routers.html',routers=cur.execute('SELECT * FROM routers').fetchall())

@app.route('/subscribers')
def subscribers():
    db=get_db(); cur=db.cursor()
    return render_template('subscribers.html',subscribers=cur.execute('SELECT * FROM subscribers ORDER BY id DESC').fetchall())

@app.route('/add-subscriber',methods=['GET','POST'])
@app.route('/add_subscriber',methods=['GET','POST'])
def add_subscriber():
    db=get_db(); cur=db.cursor()
    if request.method=='POST':
        username=request.form.get('username','').strip()
        password=request.form.get('password','').strip()
        profile=request.form.get('profile','').strip()
        phone=request.form.get('phone','').strip().replace('+','').replace(' ','')
        full_name=request.form.get('full_name','').strip()
        service_type=request.form.get('service_type','hotspot')
        start=datetime.now().strftime('%Y-%m-%d')
        expiry=(datetime.now()+timedelta(days=30)).strftime('%Y-%m-%d')
        try:
            cur.execute('INSERT INTO subscribers (username,password,profile,service_type,phone,full_name,status,start_date,expiry_date) VALUES (?,?,?,?,?,?,?,?,?)',(username,password,profile,service_type,phone,full_name,'active',start,expiry))
            db.commit()
            # اضافة على المايكروتك
            for r in cur.execute('SELECT * FROM routers').fetchall():
                api,conn,err=connect_mikrotik(r['ip_address'],r['username'],r['password'],r['port'])
                if api and not err:
                    try:
                        if service_type=='hotspot':
                            res=api.get_resource('/ip/hotspot/user')
                            if not res.get(name=username): res.add(name=username,password=password,profile=profile)
                        else:
                            res=api.get_resource('/ppp/secret')
                            if not res.get(name=username): res.add(name=username,password=password,profile=profile,service=service_type)
                    except: pass
                    finally:
                        try: conn.disconnect()
                        except: pass
            flash(f'تم إضافة {username} ✅','success')
            return redirect(url_for('subscribers'))
        except: flash('الاسم موجود مسبقا','danger'); return redirect(url_for('add_subscriber'))
    pkgs=cur.execute('SELECT * FROM packages').fetchall()
    return render_template('add_subscriber.html',packages=pkgs,sham_account=SHAM_CASH_ACCOUNT)

@app.route('/subscribers/toggle/<int:sid>')
def toggle_sub(sid):
    db=get_db(); cur=db.cursor()
    s=cur.execute('SELECT * FROM subscribers WHERE id=?',(sid,)).fetchone()
    if s:
        new_status='disabled' if s['status']=='active' else 'active'
        cur.execute('UPDATE subscribers SET status=? WHERE id=?',(new_status,sid)); db.commit()
        # طبق على المايكروتك
        for r in cur.execute('SELECT * FROM routers').fetchall():
            api,conn,err=connect_mikrotik(r['ip_address'],r['username'],r['password'],r['port'])
            if api and not err:
                try:
                    if s['service_type']=='hotspot':
                        res=api.get_resource('/ip/hotspot/user')
                        for u in res.get(name=s['username']):
                            res.set(id=u['id'],disabled='yes' if new_status=='disabled' else 'no')
                    else:
                        res=api.get_resource('/ppp/secret')
                        for u in res.get(name=s['username']):
                            res.set(id=u['id'],disabled='yes' if new_status=='disabled' else 'no')
                except: pass
                finally:
                    try: conn.disconnect()
                    except: pass
    return redirect(url_for('subscribers'))

@app.route('/subscribers/reset/<int:sid>')
def reset_sub(sid):
    db=get_db(); cur=db.cursor()
    s=cur.execute('SELECT * FROM subscribers WHERE id=?',(sid,)).fetchone()
    if s:
        # تصفير الاستهلاك و تجديد 30 يوم
        start=datetime.now().strftime('%Y-%m-%d')
        expiry=(datetime.now()+timedelta(days=30)).strftime('%Y-%m-%d')
        cur.execute('UPDATE subscribers SET start_date=?, expiry_date=?, status=? WHERE id=?',(start,expiry,'active',sid)); db.commit()
        for r in cur.execute('SELECT * FROM routers').fetchall():
            api,conn,err=connect_mikrotik(r['ip_address'],r['username'],r['password'],r['port'])
            if api and not err:
                try:
                    api.get_resource('/ip/hotspot/active').remove(id=api.get_resource('/ip/hotspot/active').get(user=s['username'])[0]['id']) if api.get_resource('/ip/hotspot/active').get(user=s['username']) else None
                except: pass
                try:
                    if s['service_type']=='hotspot':
                        api.get_resource('/ip/hotspot/user').set(id=api.get_resource('/ip/hotspot/user').get(name=s['username'])[0]['id'],bytes_in='0',bytes_out='0') if api.get_resource('/ip/hotspot/user').get(name=s['username']) else None
                except: pass
                finally:
                    try: conn.disconnect()
                    except: pass
        flash('تم التصفير والتجديد 30 يوم ✅','success')
    return redirect(url_for('subscribers'))

@app.route('/subscribers/delete/<int:sid>')
def delete_subscriber(sid):
    db=get_db(); cur=db.cursor()
    s=cur.execute('SELECT * FROM subscribers WHERE id=?',(sid,)).fetchone()
    if s:
        cur.execute('DELETE FROM subscribers WHERE id=?',(sid,)); db.commit()
        for r in cur.execute('SELECT * FROM routers').fetchall():
            api,conn,err=connect_mikrotik(r['ip_address'],r['username'],r['password'],r['port'])
            if api and not err:
                try:
                    if s['service_type']=='hotspot':
                        for u in api.get_resource('/ip/hotspot/user').get(name=s['username']): api.get_resource('/ip/hotspot/user').remove(id=u['id'])
                    else:
                        for u in api.get_resource('/ppp/secret').get(name=s['username']): api.get_resource('/ppp/secret').remove(id=u['id'])
                except: pass
                finally:
                    try: conn.disconnect()
                    except: pass
    return redirect(url_for('subscribers'))

@app.route('/packages',methods=['GET','POST'])
def packages():
    db=get_db(); cur=db.cursor()
    if request.method=='POST':
        cur.execute('INSERT INTO packages (name,rate_limit,price) VALUES (?,?,?)',(request.form.get('name'),request.form.get('rate_limit'),request.form.get('price',0))); db.commit(); return redirect(url_for('packages'))
    return render_template('packages.html',packages=cur.execute('SELECT * FROM packages').fetchall())

@app.route('/payments')
def payments():
    db=get_db(); cur=db.cursor()
    return render_template('payments.html',payments=cur.execute('SELECT * FROM payments ORDER BY id DESC').fetchall(),sham_account=SHAM_CASH_ACCOUNT)

if __name__=='__main__': app.run(host='0.0.0.0',port=5000,debug=True)
