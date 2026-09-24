from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/hotspot/login", response_class=HTMLResponse)
async def login_page(mac: str = "", ip: str = "", link_login: str = "", error: str = ""):
    return f"""
    <html dir="rtl" style="font-family:sans-serif; text-align:center; padding-top:50px">
    <h2>ZINAR NET - تجربة</h2>
    <p>MAC: {mac} | IP: {ip}</p>
    <p style="color:red">{error}</p>
    <form method="post">
      <input type="hidden" name="link_login" value="{link_login}">
      <input name="code" placeholder="دخل كود تجريبي: test123" style="padding:10px; width:200px"><br><br>
      <button style="padding:10px 30px">دخول تجريبي</button>
    </form>
    </html>
    """

@router.post("/hotspot/login", response_class=HTMLResponse)
async def check_code(code: str = Form(...), link_login: str = Form(...)):
    # هون بعدين منوصلو بقاعدة البيانات تبعك
    # هلا للتجربة منقبل اي كود
    if len(code) < 3:
        return f"<h3>كود غلط</h3><a href='/hotspot/login?link-login={{link_login}}'>رجوع</a>"

    # هاد هو يلي بيفتح النت بالمايكروتك
    return f"""
    <html><body onload="document.f.submit()">
      <p>تم التحقق، جاري فتح النت...</p>
      <form name="f" method="post" action="{link_login}">
        <input type="hidden" name="username" value="{code}">
        <input type="hidden" name="password" value="{code}">
      </form>
    </body></html>
    """
