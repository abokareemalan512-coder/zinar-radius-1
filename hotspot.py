from flask import Blueprint, request, redirect
import urllib.parse

hotspot_bp = Blueprint('hotspot', __name__)

@hotspot_bp.route('/hotspot/login', methods=['GET', 'POST'])
def hotspot_login():
    mac = request.args.get('mac', '')
    ip = request.args.get('ip', '')
    link_login = request.args.get('link-login', '') or request.form.get('link_login', '')
    link_orig = request.args.get('link-orig', '') or 'http://neverssl.com'

    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        link = request.form.get('link_login', '')

        if code != "test123":
            return f"<h1>كود غلط</h1>"

        # الحل: نحول بـ GET مو POST
        clean_link = urllib.parse.unquote(link)
        login_url = f"{clean_link}?username={code}&password={code}&dst={urllib.parse.quote(link_orig)}"
        return redirect(login_url)

    return f"""
    <html dir="rtl" style="font-family:sans-serif; text-align:center; padding-top:50px">
    <h2>ZINAR NET</h2>
    <p>MAC: {mac}</p>
    <form method="post">
      <input type="hidden" name="link_login" value="{link_login}">
      <input type="hidden" name="link_orig" value="{link_orig}">
      <input name="code" placeholder="test123" style="padding:15px; width:220px"><br><br>
      <button style="padding:12px 40px; background:#0ea5e9; color:#fff; border:none; border-radius:8px">دخول</button>
    </form>
    </html>
    """
