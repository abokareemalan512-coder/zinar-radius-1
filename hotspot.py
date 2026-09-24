from flask import Blueprint, request, redirect
import urllib.parse

hotspot_bp = Blueprint('hotspot', __name__)

@hotspot_bp.route('/hotspot/login', methods=['GET', 'POST'])
def hotspot_login():
    mac = request.args.get('mac','')
    link_login = request.args.get('link-login','') or request.form.get('link_login','')
    
    if link_login:
        link_login = urllib.parse.unquote(link_login)
    if not link_login:
        link_login = "http://13.13.13.13/login"

    if request.method == 'POST':
        code = request.form.get('code','').strip()
        if not code:
            return "<h1 style='text-align:center;margin-top:100px;font-family:sans-serif'>الرجاء كتابة الكود</h1>"
        
        login_url = f"{link_login}?username={urllib.parse.quote(code)}&password={urllib.parse.quote(code)}"
        return redirect(login_url)

    return f"""
    <html dir="rtl" lang="ar">
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
    <body style="font-family:sans-serif; background:#f0f9ff; text-align:center; padding-top:60px">
        <div style="background:white; max-width:340px; margin:auto; padding:25px; border-radius:15px; box-shadow:0 4px 15px #0002">
            <h2 style="color:#0ea5e9">شبكة زينار نت</h2>
            <p style="color:#666; font-size:12px">{mac}</p>
            <form method="post">
              <input type="hidden" name="link_login" value="{urllib.parse.quote(link_login)}">
              <input name="code" placeholder="أدخل كود الكرت هنا" style="padding:14px; width:90%; border:1px solid #ddd; border-radius:8px; text-align:center; font-size:16px"><br><br>
              <button style="padding:13px; width:95%; background:#0ea5e9; color:#fff; border:none; border-radius:8px; font-size:17px; font-weight:bold">اتصال</button>
            </form>
            <p style="margin-top:20px; font-size:11px; color:#999">للدعم الفني تواصل مع الإدارة</p>
        </div>
    </body>
    </html>
    """
