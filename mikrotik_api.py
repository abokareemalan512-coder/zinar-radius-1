# mikrotik_api.py
"""
خدمة الاتصال بـ MikroTik RouterOS عبر SSH
تدعم PPPoE (برودباند) و Hotspot

الإصدار: 2.0 — نسخة محسّنة
- إصلاح الاتصال المتداخل (double connect)
- regex parsing بدل split
- معالجة أخطاء أفضل
"""
import logging
import re
import paramiko

logger = logging.getLogger(__name__)


class MikrotikError(Exception):
    """خطأ في التعامل مع MikroTik"""
    pass


class MikrotikAPI:
    """عميل SSH للتعامل مع MikroTik RouterOS"""

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
        if self.client:
            return True
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
            self.client = None
            raise MikrotikError(f"فشل الاتصال بـ {self.host}:{self.port} — {e}")

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

    def __exit__(self, *args):
        self.disconnect()

    def execute(self, command):
        """تنفيذ أمر على MikroTik"""
        if not self.client:
            raise MikrotikError("لا يوجد اتصال — استدعِ connect() أولًا")
        try:
            _, stdout, stderr = self.client.exec_command(command, timeout=self.timeout)
            out = stdout.read().decode('utf-8', errors='ignore')
            err = stderr.read().decode('utf-8', errors='ignore')

            # كشف الفشل
            if err:
                err_lower = err.lower()
                if any(kw in err_lower for kw in ('failure', 'error', 'syntax error', 'no such')):
                    raise MikrotikError(err.strip())

            return out.strip()
        except MikrotikError:
            raise
        except Exception as e:
            raise MikrotikError(f"خطأ في التنفيذ: {e}")

    def test_connection(self):
        """اختبار الاتصال"""
        try:
            with self:
                identity = self.execute('/system identity print')
                return True, identity
        except MikrotikError as e:
            return False, str(e)

    # ============ Helpers داخلية ============

    @staticmethod
    def _quote(value):
        """حماية القيم من الرموز الخاصة"""
        if value is None:
            return '""'
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'

    @staticmethod
    def _parse_kv(text):
        """تحليل key=value مع دعم القيم بين علامات اقتباس"""
        result = {}
        pattern = r'([a-zA-Z][\w\-]*)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|(\S+))'
        for match in re.finditer(pattern, text):
            key = match.group(1).lower()
            value = match.group(2) if match.group(2) is not None else match.group(3)
            if value is not None:
                value = value.replace('\\"', '"').replace('\\\\', '\\')
            result[key] = value
        return result

    # ============ PPPoE (برودباند) ============

    def pppoe_create(self, username, password, profile='default'):
        """إنشاء مستخدم PPPoE"""
        with self:
            if self._pppoe_exists(username):
                raise MikrotikError(f"'{username}' موجود مسبقًا")
            cmd = (
                f'/ppp secret add '
                f'name={self._quote(username)} '
                f'password={self._quote(password)} '
                f'service=pppoe '
                f'profile={self._quote(profile)}'
            )
            return self.execute(cmd)

    def pppoe_delete(self, username):
        with self:
            return self.execute(f'/ppp secret remove [find name={self._quote(username)}]')

    def pppoe_enable(self, username):
        with self:
            return self.execute(f'/ppp secret enable [find name={self._quote(username)}]')

    def pppoe_disable(self, username):
        with self:
            return self.execute(f'/ppp secret disable [find name={self._quote(username)}]')

    def pppoe_exists(self, username):
        with self:
            return self._pppoe_exists(username)

    def _pppoe_exists(self, username):
        """داخلية — لا تفتح اتصالًا جديدًا"""
        output = self.execute(f'/ppp secret print where name={self._quote(username)}')
        # تحقق من وجود اسم المستخدم في المخرجات
        return f'name={username}' in output or f'name="{username}"' in output

    def pppoe_list(self):
        with self:
            return self._parse_users(self.execute('/ppp secret print detail'))

    def pppoe_active(self):
        with self:
            return self._parse_actives(self.execute('/ppp active print detail'))

    def pppoe_kick(self, username):
        with self:
            return self.execute(f'/ppp active remove [find name={self._quote(username)}]')

    # ============ Hotspot ============

    def hotspot_create(self, username, password, profile='default'):
        """إنشاء مستخدم Hotspot"""
        with self:
            if self._hotspot_exists(username):
                raise MikrotikError(f"'{username}' موجود مسبقًا")
            cmd = (
                f'/ip hotspot user add '
                f'name={self._quote(username)} '
                f'password={self._quote(password)} '
                f'profile={self._quote(profile)}'
            )
            return self.execute(cmd)

    def hotspot_delete(self, username):
        with self:
            return self.execute(f'/ip hotspot user remove [find name={self._quote(username)}]')

    def hotspot_enable(self, username):
        with self:
            return self.execute(f'/ip hotspot user enable [find name={self._quote(username)}]')

    def hotspot_disable(self, username):
        with self:
            return self.execute(f'/ip hotspot user disable [find name={self._quote(username)}]')

    def hotspot_exists(self, username):
        with self:
            return self._hotspot_exists(username)

    def _hotspot_exists(self, username):
        """داخلية"""
        output = self.execute(f'/ip hotspot user print where name={self._quote(username)}')
        return f'name={username}' in output or f'name="{username}"' in output

    def hotspot_list(self):
        with self:
            return self._parse_users(self.execute('/ip hotspot user print detail'))

    def hotspot_active(self):
        with self:
            return self._parse_actives(self.execute('/ip hotspot active print detail'))

    def hotspot_kick(self, username):
        with self:
            return self.execute(f'/ip hotspot active remove [find user={self._quote(username)}]')

    # ============ Universal — حسب النوع ============

    def user_create(self, username, password, user_type='pppoe', profile='default'):
        if user_type == 'hotspot':
            return self.hotspot_create(username, password, profile)
        return self.pppoe_create(username, password, profile)

    def user_delete(self, username, user_type='pppoe'):
        if user_type == 'hotspot':
            return self.hotspot_delete(username)
        return self.pppoe_delete(username)

    def user_enable(self, username, user_type='pppoe'):
        if user_type == 'hotspot':
            return self.hotspot_enable(username)
        return self.pppoe_enable(username)

    def user_disable(self, username, user_type='pppoe'):
        if user_type == 'hotspot':
            return self.hotspot_disable(username)
        return self.pppoe_disable(username)

    def user_kick(self, username, user_type='pppoe'):
        if user_type == 'hotspot':
            return self.hotspot_kick(username)
        return self.pppoe_kick(username)

    def user_update_password(self, username, new_password, user_type='pppoe'):
        with self:
            if user_type == 'hotspot':
                cmd = (f'/ip hotspot user set [find name={self._quote(username)}] '
                       f'password={self._quote(new_password)}')
            else:
                cmd = (f'/ppp secret set [find name={self._quote(username)}] '
                       f'password={self._quote(new_password)}')
            return self.execute(cmd)

    def user_update_profile(self, username, new_profile, user_type='pppoe'):
        with self:
            if user_type == 'hotspot':
                cmd = (f'/ip hotspot user set [find name={self._quote(username)}] '
                       f'profile={self._quote(new_profile)}')
            else:
                cmd = (f'/ppp secret set [find name={self._quote(username)}] '
                       f'profile={self._quote(new_profile)}')
            return self.execute(cmd)

    def profiles_list(self, user_type='pppoe'):
        """قائمة Profiles المتاحة"""
        with self:
            if user_type == 'hotspot':
                cmd = '/ip hotspot user profile print detail'
            else:
                cmd = '/ppp profile print detail'
            output = self.execute(cmd)
            profiles = []
            seen = set()
            for match in re.finditer(r'name="?([^"\s]+)"?', output):
                name = match.group(1)
                if name not in seen:
                    seen.add(name)
                    profiles.append(name)
            return profiles

    # ============ Parsing ============

    def _parse_users(self, output):
        """تحليل مخرجات print detail للمستخدمين"""
        users = []
        current = {}
        for line in output.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue

            # بداية سجل جديد
            if stripped[0].isdigit() and ('name=' in stripped or 'user=' in stripped):
                if current:
                    users.append(current)
                current = self._parse_kv(stripped)
            elif current:
                # استكمال السجل الحالي
                current.update(self._parse_kv(stripped))

        if current:
            users.append(current)
        return users

    def _parse_actives(self, output):
        """تحليل مخرجات print detail للاتصالات النشطة"""
        actives = []
        current = {}
        for line in output.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue

            if stripped[0].isdigit():
                if current:
                    actives.append(current)
                current = self._parse_kv(stripped)
            elif current:
                current.update(self._parse_kv(stripped))

        if current:
            actives.append(current)
        return actives

    # ============ استيراد من ملف .rsc ============

    def import_rsc_content(self, content):
        """
        تحليل محتوى ملف .rsc من MikroTik
        يعيد: {'pppoe': [...], 'hotspot': [...]}
        """
        result = {'pppoe': [], 'hotspot': []}
        current_section = None

        for raw_line in content.split('\n'):
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue

            # تحديد القسم
            if line.startswith('/ppp secret'):
                current_section = 'pppoe'
                if ' add ' in line or line.startswith('/ppp secret add'):
                    user = self._parse_rsc_add(line)
                    if user:
                        result['pppoe'].append(user)
                continue

            if line.startswith('/ip hotspot user'):
                current_section = 'hotspot'
                if ' add ' in line or line.startswith('/ip hotspot user add'):
                    user = self._parse_rsc_add(line)
                    if user:
                        result['hotspot'].append(user)
                continue

            # أسطر add لاحقة
            if line.startswith('add ') and current_section:
                user = self._parse_rsc_add(line)
                if user:
                    result[current_section].append(user)

        return result

    def _parse_rsc_add(self, line):
        """تحليل سطر add من ملف .rsc"""
        user = self._parse_kv(line)
        return user if user.get('name') else None


# ============ دوال مساعدة ============

def get_router_api(router):
    """إنشاء كائن MikrotikAPI من كائن Router"""
    return MikrotikAPI(
        host=router.ip_address,
        username=router.username,
        password=router.password,
        port=router.port or 22,
        timeout=10,
    )


def test_router_connection(router):
    """اختبار اتصال راوتر"""
    try:
        api = get_router_api(router)
        return api.test_connection()
    except Exception as e:
        return False, str(e)


def kick_user(router, username, user_type='pppoe'):
    """قطع اتصال مستخدم"""
    try:
        api = get_router_api(router)
        return api.user_kick(username, user_type)
    except MikrotikError as e:
        logger.warning(f"kick_user({username}) فشل: {e}")
        return False
