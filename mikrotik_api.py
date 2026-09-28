# mikrotik_api.py
"""
خدمة الاتصال بـ Mikrotik RouterOS عبر SSH (Paramiko)
تسمح بإنشاء/حذف/تفعيل/إيقاف مستخدمي PPPoE تلقائيًا
"""
import logging
import paramiko

logger = logging.getLogger(__name__)


class MikrotikError(Exception):
    """خطأ في Mikrotik"""
    pass


class MikrotikAPI:
    """عميل SSH للتحكم في Mikrotik"""

    def __init__(self, host, username, password, port=22, timeout=10):
        self.host = host
        self.username = username
        self.password = password
        self.port = port or 22
        self.timeout = timeout
        self.client = None

    # ============ الاتصال ============

    def connect(self):
        """فتح اتصال SSH"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=self.timeout,
                allow_agent=False,
                look_for_keys=False,
            )
            return True
        except Exception as e:
            logger.error(f"❌ فشل الاتصال بـ {self.host}: {e}")
            raise MikrotikError(f"فشل الاتصال: {str(e)}")

    def disconnect(self):
        """إغلاق الاتصال"""
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    # ============ تنفيذ الأوامر ============

    def execute(self, command):
        """تنفيذ أمر RouterOS وإرجاع النتيجة"""
        if not self.client:
            raise MikrotikError("لا يوجد اتصال نشط")
        try:
            stdin, stdout, stderr = self.client.exec_command(command)
            output = stdout.read().decode('utf-8', errors='ignore')
            error = stderr.read().decode('utf-8', errors='ignore')
            if error and 'failure' in error.lower():
                raise MikrotikError(error.strip())
            return output.strip()
        except MikrotikError:
            raise
        except Exception as e:
            raise MikrotikError(f"خطأ في التنفيذ: {str(e)}")

    # ============ اختبار الاتصال ============

    def test_connection(self):
        """اختبار سريع للاتصال"""
        try:
            with self:
                result = self.execute('/system identity print')
                return True, result
        except MikrotikError as e:
            return False, str(e)

    # ============ معلومات النظام ============

    def get_identity(self):
        """اسم الراوتر"""
        with self:
            return self.execute('/system identity print')

    def get_resource(self):
        """موارد النظام (CPU, RAM, Uptime)"""
        with self:
            return self.execute('/system resource print')

    # ============ إدارة المستخدمين (PPPoE Secrets) ============

    def list_users(self):
        """قائمة كل مستخدمي PPPoE"""
        with self:
            output = self.execute('/ppp secret print detail')
            users = []
            current = {}
            for line in output.split('\n'):
                line = line.strip()
                # بداية مستخدم جديد
                if line and (line[0].isdigit()) and 'name=' in line:
                    if current:
                        users.append(current)
                    current = {}
                for part in line.split():
                    if part.startswith('name='):
                        current['name'] = part.replace('name=', '').strip('"')
                    elif part.startswith('service='):
                        current['service'] = part.replace('service=', '').strip('"')
                    elif part.startswith('profile='):
                        current['profile'] = part.replace('profile=', '').strip('"')
                    elif part.startswith('disabled='):
                        current['disabled'] = part.replace('disabled=', '').strip('"')
            if current:
                users.append(current)
            return users

    def user_exists(self, username):
        """هل المستخدم موجود؟"""
        with self:
            output = self.execute(f'/ppp secret print where name="{username}"')
            return username in output

    def create_user(self, username, password, profile='default', service='pppoe'):
        """إنشاء مستخدم PPPoE جديد"""
        with self:
            if self.user_exists(username):
                raise MikrotikError(f"المستخدم '{username}' موجود مسبقًا")

            cmd = (
                f'/ppp secret add '
                f'name="{username}" '
                f'password="{password}" '
                f'service={service} '
                f'profile="{profile}"'
            )
            return self.execute(cmd)

    def delete_user(self, username):
        """حذف مستخدم"""
        with self:
            cmd = f'/ppp secret remove [find name="{username}"]'
            return self.execute(cmd)

    def enable_user(self, username):
        """تفعيل مستخدم"""
        with self:
            cmd = f'/ppp secret enable [find name="{username}"]'
            return self.execute(cmd)

    def disable_user(self, username):
        """إيقاف مستخدم"""
        with self:
            cmd = f'/ppp secret disable [find name="{username}"]'
            return self.execute(cmd)

    def update_user_password(self, username, new_password):
        """تغيير كلمة مرور مستخدم"""
        with self:
            cmd = f'/ppp secret set [find name="{username}"] password="{new_password}"'
            return self.execute(cmd)

    def update_user_profile(self, username, new_profile):
        """تغيير باقة (profile) مستخدم"""
        with self:
            cmd = f'/ppp secret set [find name="{username}"] profile="{new_profile}"'
            return self.execute(cmd)

    def disconnect_active_user(self, username):
        """قطع الاتصال النشط لمستخدم"""
        with self:
            cmd = f'/ppp active remove [find name="{username}"]'
            return self.execute(cmd)

    # ============ الباقات (Profiles) ============

    def list_profiles(self):
        """قائمة الباقات المتاحة"""
        with self:
            output = self.execute('/ppp profile print detail')
            profiles = []
            for line in output.split('\n'):
                line = line.strip()
                if 'name=' in line:
                    for part in line.split():
                        if part.startswith('name='):
                            name = part.replace('name=', '').strip('"')
                            if name and name not in profiles:
                                profiles.append(name)
            return profiles

    # ============ الاتصالات النشطة ============

    def list_active(self):
        """قائمة الاتصالات النشطة"""
        with self:
            output = self.execute('/ppp active print detail')
            actives = []
            current = {}
            for line in output.split('\n'):
                line = line.strip()
                if line and (line[0].isdigit()) and 'name=' in line:
                    if current:
                        actives.append(current)
                    current = {}
                for part in line.split():
                    if part.startswith('name='):
                        current['name'] = part.replace('name=', '').strip('"')
                    elif part.startswith('address='):
                        current['address'] = part.replace('address=', '').strip('"')
                    elif part.startswith('uptime='):
                        current['uptime'] = part.replace('uptime=', '').strip('"')
                    elif part.startswith('service='):
                        current['service'] = part.replace('service=', '').strip('"')
            if current:
                actives.append(current)
            return actives

    def count_active(self):
        """عدد الاتصالات النشطة"""
        with self:
            output = self.execute('/ppp active print count-only')
            try:
                return int(output.strip())
            except ValueError:
                return 0


# ============ دوال مساعدة ============

def get_router_api(router):
    """إنشاء كائن API من نموذج Router"""
    return MikrotikAPI(
        host=router.ip_address,
        username=router.username,
        password=router.password,
        port=router.port or 22,
        timeout=10,
    )


def test_router_connection(router):
    """اختبار الاتصال بالراوتر"""
    try:
        api = get_router_api(router)
        return api.test_connection()
    except Exception as e:
        return False, str(e)
