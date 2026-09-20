import socket
import binascii

class MikroTikAPI:
    def __init__(self, host, port=8728, username='admin', password=''):
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.sock = None

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect((self.host, self.port))

    def login(self):
        self._write(['/login', '=name=' + self.username, '=password=' + self.password])
        self._read()

    def _write(self, words):
        for w in words:
            self._send_len(len(w))
            self.sock.send(w.encode('utf-8'))
        self.sock.send(b'\x00')

    def _send_len(self, length):
        if length < 0x80:
            self.sock.send(bytes([length]))
        elif length < 0x4000:
            length |= 0x8000
            self.sock.send(bytes([(length >> 8) & 0xFF, length & 0xFF]))
        elif length < 0x200000:
            length |= 0xC00000
            self.sock.send(bytes([(length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF]))
        elif length < 0x10000000:
            length |= 0xE0000000
            self.sock.send(bytes([(length >> 24) & 0xFF, (length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF]))
        else:
            self.sock.send(bytes([0xF0, (length >> 24) & 0xFF, (length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF]))

    def _read(self):
        reply = []
        while True:
            sentence = []
            while True:
                length = self._read_len()
                if length == 0:
                    break
                received = self.sock.recv(length).decode('utf-8', errors='ignore')
                sentence.append(received)
            if not sentence:
                break
            reply.append(sentence)
            if sentence[0] == '!done':
                break
        return reply

    def _read_len(self):
        byte = self.sock.recv(1)
        if not byte:
            return 0
        length = ord(byte)
        if (length & 0x80) == 0x00:
            return length
        elif (length & 0xC0) == 0x80:
            return ((length & 0x3F) << 8) + ord(self.sock.recv(1))
        elif (length & 0xE0) == 0xC0:
            return ((length & 0x1F) << 16) + (ord(self.sock.recv(1)) << 8) + ord(self.sock.recv(1))
        elif (length & 0xF0) == 0xE0:
            return ((length & 0x0F) << 24) + (ord(self.sock.recv(1)) << 16) + (ord(self.sock.recv(1)) << 8) + ord(self.sock.recv(1))
        elif (length & 0xF8) == 0xF0:
            return (ord(self.sock.recv(1)) << 24) + (ord(self.sock.recv(1)) << 16) + (ord(self.sock.recv(1)) << 8) + ord(self.sock.recv(1))
        return 0

    def add_pppoe_user(self, username, password, profile):
        try:
            self.connect()
            self.login()
            self._write(['/ppp/secret/add', '=name=' + username, '=password=' + password, '=profile=' + profile])
            self._read()
            self.sock.close()
        except Exception as e:
            print(f"MikroTik Error: {e}")

    def remove_pppoe_user(self, username):
        try:
            self.connect()
            self.login()
            self._write(['/ppp/secret/print', '?.proplist=.id', '=name=' + username])
            resp = self._read()
            for sentence in resp:
                if '!re' in sentence:
                    for item in sentence:
                        if item.startswith('=id='):
                            uid = item.split('=')[1]
                            self._write(['/ppp/secret/remove', '=.id=' + uid])
                            self._read()
            self.sock.close()
        except Exception as e:
            print(f"MikroTik Error: {e}")
