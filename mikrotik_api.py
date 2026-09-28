# mikrotik_api.py
"""
خدمة الاتصال بـ Mikrotik RouterOS عبر SSH
تدعم Hotspot و PPPoE
"""
import logging
import re
import paramiko

logger = logging.getLogger(__name__)


class MikrotikError(Exception):
    pass


class MikrotikAPI:

    def __init__(self, host, username, password, port=22, timeout=10):
        self.host = host
        self.username = username
        self.password = password
        self.port = port or 22
        self.timeout = timeout
        self.client = None

    def connect(self):
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(
                hostname=self.host, port=self.port,
                username=self.username, password=self.password,
                timeout=self.timeout, allow_agent=False, look_for_keys=False,
            )
            return True
        except Exception as e:
            raise MikrotikError(f"فشل الاتصال: {str(e)}")

    def disconnect(self):
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
        if not self.client:
            raise MikrotikError("لا يوجد اتصال")
        try:
            _, stdout, stderr = self.client.exec_command(command)
            out = stdout.read().decode('utf-8', errors='ignore')
            err = stderr.read().decode('utf-8', errors='ignore')
            if err and 'failure' in err.lower():
                raise MikrotikError(err.strip())
            return out.strip()
        except MikrotikError:
            raise
        except Exception as e:
            raise MikrotikError(f"خطأ: {str(e)}")

    def test_connection(self):
        try:
            with self:
                return True, self.execute('/system identity print')
        except MikrotikError as e:
            return False, str(e)

    # ============ PPPoE (برودباند) ============

    def pppoe_create(self, username, password, profile='default'):
        with self:
            if self.pppoe_exists(username):
                raise MikrotikError(f"'{username}' موجود مسبقًا")
            cmd = (f'/ppp secret add name="{username}" '
                   f'password="{password}" service=pppoe profile="{profile}"')
            return self.execute(cmd)

    def pppoe_delete(self, username):
        with self:
            return self.execute(f'/ppp secret remove [find name="{username}"]')

    def pppoe_enable(self, username):
        with self:
            return self.execute(f'/ppp secret enable [find name="{username}"]')

    def pppoe_disable(self, username):
        with self:
            return self.execute(f'/ppp secret disable [find name="{username}"]')

    def pppoe_exists(self, username):
        with self:
            return username in self.execute(f'/ppp secret print where name="{username}"')

    def pppoe_list(self):
        with self:
            return self._parse_users(self.execute('/ppp secret print detail'))

    def pppoe_active(self):
        with self:
            return self._parse_actives(self.execute('/ppp active print detail'))

    def pppoe_kick(self, username):
        with self:
            return self.execute(f'/ppp active remove [find name="{username}"]')

    # ============ Hotspot ============

    def hotspot_create(self, username, password, profile='default'):
        with self:
            if self.hotspot_exists(username):
                raise MikrotikError(f"'{username}' موجود مسبقًا")
            cmd = (f'/ip hotspot user add name="{username}" '
                   f'password="{password}" profile="{profile}"')
            return self.execute(cmd)

    def hotspot_delete(self, username):
        with self:
            return self.execute(f'/ip hotspot user remove [find name="{username}"]')

    def hotspot_enable(self, username):
        with self:
            return self.execute(f'/ip hotspot user enable [find name="{username}"]')

    def hotspot_disable(self, username):
        with self:
            return self.execute(f'/ip hotspot user disable [find name="{username}"]')

    def hotspot_exists(self, username):
        with self:
            return username in self.execute(f'/ip hotspot user print where name="{username}"')

    def hotspot_list(self):
        with self:
            return self._parse_users(self.execute('/ip hotspot user print detail'))

    def hotspot_active(self):
        with self:
            return self._parse_actives(self.execute('/ip hotspot active print detail'))

    def hotspot_kick(self, username):
        with self:
            return self.execute(f'/ip hotspot active remove [find user="{username}"]')

    # ============ Universal (حسب النوع) ============

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
        if user_type == 'hotspot':
            with self:
                return self.execute(f'/ip hotspot user set [find name="{username}"] password="{new_password}"')
        with self:
            return self.execute(f'/ppp secret set [find name="{username}"] password="{new_password}"')

    def user_update_profile(self, username, new_profile, user_type='pppoe'):
        if user_type == 'hotspot':
            with self:
                return self.execute(f'/ip hotspot user set [find name="{username}"] profile="{new_profile}"')
        with self:
            return self.execute(f'/ppp secret set [find name="{username}"] profile="{new_profile}"')

    def profiles_list(self, user_type='pppoe'):
        if user_type == 'hotspot':
            cmd = '/ip hotspot user profile print detail'
        else:
            cmd = '/ppp profile print detail'
        with self:
            output = self.execute(cmd)
            profiles = []
            for line in output.split('\n'):
                for part in line.split():
                    if part.startswith('name='):
                        name = part.replace('name=', '').strip('"')
                        if name and name not in profiles:
                            profiles.append(name)
            return profiles

    # ============ Parsing ============

    def _parse_users(self, output):
        users = []
        current = {}
        for line in output.split('\n'):
            line = line.strip()
            if line and line[0].isdigit() and 'name=' in line:
                if current:
                    users.append(current)
                current = {}
            for part in line.split():
                for key in ('name', 'password', 'profile', 'service', 'disabled', 'limit-uptime'):
                    if part.startswith(f'{key}='):
                        current[key] = part.replace(f'{key}=', '').strip('"')
        if current:
            users.append(current)
        return users

    def _parse_actives(self, output):
        actives = []
        current = {}
        for line in output.split('\n'):
            line = line.strip()
            if line and line[0].isdigit():
                if current:
                    actives.append(current)
                current = {}
            for part in line.split():
                for key in ('name', 'user', 'address', 'uptime', 'service', 'mac-address'):
                    if part.startswith(f'{key}='):
                        current[key] = part.replace(f'{key}=', '').strip('"')
        if current:
            actives.append(current)
        return actives

    # ============ استيراد من ملف .rsc ============

    def import_rsc_content(self, content):
        """
        تحليل محتوى ملف .rsc من Mikrotik
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
                # قد يحتوي على add على نفس السطر
                if ' add ' in line:
                    user = self._parse_rsc_add(line)
                    if user:
                        result['pppoe'].append(user)
                continue
            elif line.startswith('/ip hotspot user'):
                current_section = 'hotspot'
                if ' add ' in line:
                    user = self._parse_rsc_add(line)
                    if user:
                        result['hotspot'].append(user)
                continue

            # أسطر إضافية
            if line.startswith('add ') and current_section:
                user = self._parse_rsc_add(line)
                if user:
                    result[current_section].append(user)

        return result

    def _parse_rsc_add(self, line):
        """تحليل سطر add من ملف .rsc"""
        user = {}
        # البحث عن name="xxx"
        patterns = {
            'name': r'name=("([^"]+)"|\S+)',
            'password': r'password=("([^"]+)"|\S+)',
            'profile': r'profile=("([^"]+)"|\S+)',
            'service': r'service=("([^"]+)"|\S+)',
            'disabled': r'disabled=("([^"]+)"|\S+)',
        }
        for key, pattern in patterns.items():
            m = re.search(pattern, line)
            if m:
                val = m.group(2) or m.group(1)
                user[key] = val.strip('"')
        return user if user.get('name') else None


# ============ دوال مساعدة ============

def get_router_api(router):
    return MikrotikAPI(
        host=router.ip_address,
        username=router.username,
        password=router.password,
        port=router.port or 22,
        timeout=10,
    )


def test_router_connection(router):
    try:
        api = get_router_api(router)
        return api.test_connection()
    except Exception as e:
        return False, str(e)
