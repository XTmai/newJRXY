"""今日校园 CLOUD(joinType=CLOUD) 学校的 IAP 登录实现

2026-09-04 实测修正（网页版登录流程）：
学校已升级登录接口，App 老流程（query 参数 + AES(salt) 密码）返回 FAIL_UPNOTMATCH，
网页版实际流程为：
    1. GET  {host}iap/login?service=...     -> 302 建立 CONVERSATION 会话 + _2lBepC
    2. POST {host}iap/security/lt           -> 取 _lt（JSON body {}）
    3. 密码 RSA 加密: "{rsa}" + base64(RSA_PKCS1v15(密码))，公钥硬编码于登录页 JS
    4. POST {host}iap/doLogin               -> form-urlencoded body（非 query!）
       头: X-Requested-With + deviceId + fingerprintId
       成功响应: 200 {"resultCode":"REDIRECT","url":"/"} + Set-Cookie CASTGC
    5. GET  {host}iap/login?service=...     -> 302 携 ticket -> 业务域 MOD_AUTH_CAS
风控: 连续失败后 doLogin 返回 CAPTCHA_NOTMATCH+needCaptcha，此时:
    GET {host}iap/generateCaptcha?ltId={lt} 取图片验证码（与 lt 绑定）
    通过 captcha_provider 回调获取识别文本后重试。
"""

import base64
import random
import uuid

from cryptography.hazmat.primitives.asymmetric import padding as _rsa_padding
from cryptography.hazmat.primitives.serialization import load_der_public_key

# 登录页 chunk-common.js 内嵌 RSA 公钥（1024bit, SPKI/DER base64）
IAP_RSA_PUBLIC_KEY = (
    'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDCpbRy8ZoyQvRPpUDIXycglTwVDcYr'
    'Lcv7P9HI4E7/TAPZiI3GN0ckTUVVWRvoo/re3uCOOJK+F+Ufh19XiRIdoPYCULsSyEjcL'
    'LiyAS09mVOzhAQco84E/lM24T7rRTVID7LIgWPewyN8Nd5vzHET4Q3qTthoL8n82BwC1i'
    'XuVQIDAQAB'
)
_SERVICE_PATH = 'wec-counselor-attendance-apps/student/mobileStudent/index.html'
_PUB = None


def rsa_encrypt_password(password):
    """网页版登录密码格式: '{rsa}' + base64(RSA-PKCS1v15(password))"""
    global _PUB
    if _PUB is None:
        _PUB = load_der_public_key(base64.b64decode(IAP_RSA_PUBLIC_KEY))
    ct = _PUB.encrypt(password.encode('utf-8'), _rsa_padding.PKCS1v15())
    return '{rsa}' + base64.b64encode(ct).decode()

import base64
import json
import random

from Crypto.Cipher import AES

RAND_BASE = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"
# 与客户端一致的固定 IV
FIXED_IV = bytes([1, 2, 3, 4, 5, 6, 7, 8, 9, 1, 2, 3, 4, 5, 6, 7])


def rand_string(length):
    return ''.join(random.choice(RAND_BASE) for _ in range(length))


def encrypt_password(password, salt):
    """用服务端下发的 _encryptSalt 对密码做 AES-CBC 加密。

    无 salt 时退回明文（与客户端行为一致，仍走 HTTPS）。
    """
    if not salt:
        return password

    data = rand_string(64) + password
    pad_len = AES.block_size - (len(data) % AES.block_size)
    if pad_len == 0:
        pad_len = AES.block_size
    data += chr(pad_len) * pad_len

    # IV 固定即可：明文前 64 字节是随机填充，密码落在第 5 个块之后，
    # CBC 从第 2 个块起解密不依赖 IV，服务端侧不受影响。
    aes = AES.new(salt.encode('utf-8'), AES.MODE_CBC, FIXED_IV)
    # 必须用 b64encode：encodebytes 每 76 字符会插入换行，
    # 而前端 CryptoJS 输出的是连续 base64，换行会导致服务端解析失败。
    return base64.b64encode(aes.encrypt(data.encode('utf-8'))).decode('utf-8')


class IapLogin:
    def __init__(self, username, password, host, session, on_log=None, captcha_provider=None):
        self.username = username
        self.password = password
        self.host = host if host.endswith('/') else host + '/'
        self.session = session
        self.on_log = on_log or (lambda m: None)
        # captcha_provider(image_bytes) -> str：需要验证码时的识别回调
        self.captcha_provider = captcha_provider

    def log(self, msg):
        self.on_log(msg)

    def _entry(self):
        """访问登录入口，建立 CONVERSATION 会话（302 -> mobile.html?_2lBepC=...)"""
        self.session.get(self.host + 'iap/login',
                         params={'service': self.host + _SERVICE_PATH},
                         verify=False, timeout=15)

    def _fetch_captcha(self, lt):
        """下载与 lt 绑定的图形验证码，经 captcha_provider 识别"""
        r = self.session.get(self.host + 'iap/generateCaptcha',
                             params={'ltId': lt, 'random': random.random()},
                             verify=False, timeout=15)
        if self.captcha_provider is None:
            raise Exception('服务端要求图形验证码，但未提供 captcha_provider')
        return self.captcha_provider(r.content)

    def _device_headers(self):
        return {'X-Requested-With': 'XMLHttpRequest',
                'deviceId': str(uuid.uuid4()),
                'fingerprintId': str(uuid.uuid4())}

    def get_lt(self):
        r = self.session.post(self.host + 'iap/security/lt',
                              data=json.dumps({}), verify=False, timeout=15,
                              headers={'Content-Type': 'application/json',
                                       'X-Requested-With': 'XMLHttpRequest'})
        return r.json()['result']

    def login(self):
        self._entry()

        lt_info = self.get_lt()
        lt = lt_info['_lt']
        if lt_info.get('needCaptcha'):
            # lt 下发时即要求验证码：先取一张
            captcha = self._fetch_captcha(lt)
            self.log(f'前置验证码: {captcha}')
        else:
            captcha = ''

        pwd = rsa_encrypt_password(self.password)
        self.log('密码已 RSA 加密（网页版 {rsa} 格式）')

        def do_post(captcha_value):
            body = {'username': self.username, 'password': pwd, 'lt': lt,
                    'dllt': '', 'mobile': '', 'captcha': captcha_value,
                    'rememberMe': 'false'}
            return self.session.post(
                self.host + 'iap/doLogin', data=body,
                headers=self._device_headers(),
                verify=False, timeout=15, allow_redirects=False)

        r = do_post(captcha)
        # 失败次数累计后服务端要求验证码：CAPTCHA_NOTMATCH -> 取图重试一次
        if r.status_code == 200 and 'CAPTCHA_NOTMATCH' in r.text:
            self.log('服务端要求图形验证码，正在获取...')
            captcha2 = self._fetch_captcha(lt)
            self.log(f'验证码: {captcha2}')
            r = do_post(captcha2)

        if r.status_code == 302:
            self.session.get(r.headers['Location'], verify=False, timeout=15)
            self.log('IAP 登录成功')
            return True

        try:
            data = r.json()
        except Exception:
            raise Exception(f'登录失败: HTTP {r.status_code}')

        code = data.get('resultCode')
        if code == 'REDIRECT':
            # 登录成功（服务端已种 CASTGC），换业务域 service 票
            r2 = self.session.get(self.host + 'iap/login',
                                  params={'service': self.host + _SERVICE_PATH},
                                  verify=False, timeout=15)
            self.log(f'IAP 登录成功（service 票 HTTP {r2.status_code}）')
            return True
        if code == 'FAIL_UPNOTMATCH':
            raise Exception('用户名或密码不正确')
        if code == 'CAPTCHA_NOTMATCH':
            raise Exception('验证码错误（或识别失败）')
        raise Exception(f'登录失败，返回码: {code}')
