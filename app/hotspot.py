from flask import Blueprint, request

hotspot_bp = Blueprint('hotspot', __name__)

@hotspot_bp.route('/hotspot/login', methods=['GET', 'POST'])
def hotspot_login():
    mac = request.args.get('mac','')
    ip = request.args.get('ip','')
    link_login = request.args.get('link-login','') or request.form.get('link_login','')
    error = request.args.get('error','')

    if request.method == 'POST':
        code = request.form.get('code','').strip()
        link = request.form.get('link_login','')
        if len(code) < 3:
            return f"<h3>كود غلط</h3><a href='/hotspot/login?link-login={link}'>رجوع</a>"
        # هون بيفتح النت
        return f"""
        <html><body onload="document.f.submit()">
          <p>تم التحقق، جاري فتح النت...</p>
          <form name="f" method="post" action="{link}">
            <input type="hidden" name="username" value="{code}">
            <input type="hidden" name="password" value="{code}">
          </form>
        </body></html>
        """

    return f"""
    <html dir="rtl" style="font-family:sans-serif; text-align:center; padding-top:50px">
    <h2>ZINAR NET - تجربة</h2>
    <p>MAC: {mac} | IP: {ip}</p>
    <p style="color:red">{error}</p>
    <form method="post">
      <input type="hidden" name="link_login" value="{link_login}">
      <input name="code" placeholder="دخل كود تجريبي: test123" style="padding:15px; width:220px"><br><br>
      <button style="padding:10px 30px">دخول تجريبي</button>
    </form>
    </html>
    """
