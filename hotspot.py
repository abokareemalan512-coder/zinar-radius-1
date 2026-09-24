from flask import Blueprint, request, redirect
import urllib.parse

hotspot_bp = Blueprint('hotspot', __name__)

@hotspot_bp.route('/hotspot/login', methods=['GET', 'POST'])
def hotspot_login():
    mac = request.args.get('mac','')
    link_login = request.args.get('link-login','') or request.form.get('link_login','')
    link_orig = request.args.get('link-orig','') or 'http://neverssl.com'
    
    # فك التشفير
    if link_login:
        link_login = urllib.parse.unquote(link_login)

    if request.method == 'POST':
        code = request.form.get('code','').strip()
        link = request.form.get('link_login','')
        if link:
            link = urllib.parse.unquote(link)
        
        # اذا الرابط فاضي نحط الافتراضي
        if not link:
            link = "http://13.13.13.13/login"

        if not code:
            return "<h1>اكتب كود</h1>"

        # هذا هو الحل النهائي - تحويل GET
        login_url = f"{link}?username={urllib.parse.quote(code)}&password={urllib.parse.quote(code)}"
        print(f"Redirecting to: {login_url}") # رح يبين بـ Render logs
        return redirect(login_url)

    return f"""
    <html dir="rtl" style="text-align:center; padding-top:50px; font-family:sans-serif">
    <h2>ZINAR NET</h2>
    <p>{mac}</p>
    <p style="font-size:10px; color:gray">{link_login}</p>
    <form method="post">
      <input type="hidden" name="link_login" value="{urllib.parse.quote(link_login)}">
      <input name="code" placeholder="test123" style="padding:15px; width:220px"><br><br>
      <button style="padding:12px 40px; background:#0ea5e9; color:#fff; border:none; border-radius:8px">دخول</button>
    </form>
    </html>
    """
