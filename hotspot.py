from flask import Blueprint, request, redirect
import urllib.parse

hotspot_bp = Blueprint('hotspot', __name__)

@hotspot_bp.route('/hotspot/login', methods=['GET', 'POST'])
def hotspot_login():
    mac = request.args.get('mac','')
    link_login = request.args.get('link-login','') or request.form.get('link_login','')
    link_orig = request.args.get('link-orig','') or 'http://neverssl.com'

    if request.method == 'POST':
        code = request.form.get('code','').strip()
        link = request.form.get('link_login','')

        # للتجربة رح نقبل اي كود مو فاضي
        if not code:
            return "<h1>كود غلط - اكتب test123</h1>"

        clean_link = urllib.parse.unquote(link)
        login_url = f"{clean_link}?username={code}&password={code}"
        return redirect(login_url)

    return f"""
    <html dir="rtl" style="text-align:center; padding-top:50px; font-family:sans-serif">
    <h2>ZINAR NET</h2>
    <p>{mac}</p>
    <form method="post">
      <input type="hidden" name="link_login" value="{link_login}">
      <input name="code" placeholder="اكتب اي كود" style="padding:15px; width:220px"><br><br>
      <button style="padding:12px 40px; background:#0ea5e9; color:#fff; border:none; border-radius:8px">دخول</button>
    </form>
    </html>
    """
