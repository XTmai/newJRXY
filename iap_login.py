"""
IAP 统一认证登录（campusphere 平台 /iap/login）
适用 joinType=CLOUD 的学校（账号 + 密码 + 验证码，明文提交）

适配要点（示例大学 example.campusphere.net）：
1. 密码明文提交：该校登录页 JS 未调用 encryptPassword；
2. 完整跟随 CAS 重定向链：doLogin -> /portal/login 约 4 跳，最终签发 MOD_AUTH_CAS；
3. 切勿携带 X-Requested-With 头：会导致服务端返回 JSON 而中断 CAS 链。
"""
import json
import requests

requests.packages.urllib3.disable_warnings(
    requests.packages.urllib3.exceptions.InsecureRequestWarning)


class IAPLogin:
    """IAP 账号密码登录器"""

    def __init__(self, session, campus_host, username, password, on_log=None):
        """
        :param session: 复用的 requests.Session
        :param campus_host: https://xxx.campusphere.net/
        :param username: 学号/工号
        :param password: 登录密码
        :param on_log: 日志回调 f(msg)
        """
        self.session = session
        self.campus_host = campus_host.rstrip('/')
        self.username = username
        self.password = password
        self.on_log = on_log
        self.count = 0

    # -------- 工具 --------

    def log(self, msg):
        if self.on_log:
            self.on_log(msg)

    def _post_api(self, path, data=None, **kwargs):
        """向校园域名下的接口发请求（默认 JSON body，不带 X-Requested-With）"""
        return self.session.post(
            self.campus_host + path, data=data, verify=False, timeout=kwargs.pop('timeout', 15), **kwargs)

    # -------- 登录流程 --------

    def check_need_captcha(self):
        """风控判断：多次试错会触发 needCaptcha"""
        try:
            r = self._post_api('/iap/checkNeedCaptcha?username=' + self.username,
                               data=json.dumps({})).json()
            return bool(r.get('needCaptcha', False))
        except Exception:
            return False

    def get_captcha_image(self, lt):
        """下载验证码图片，返回 bytes"""
        url = f'{self.campus_host}/iap/generateCaptcha?ltId={lt}'
        return self.session.get(url, verify=False, timeout=15).content

    def login(self, captcha_prompt=None):
        """
        执行登录，成功返回会话 cookies；失败抛异常。

        :param captcha_prompt: 验证码输入回调 f(img_bytes) -> str，
                               缺省时自动保存图片并调用 input()
        """
        # 1. 获取 lt（一次性票据）
        lt_res = self._post_api('/iap/security/lt', data=json.dumps({})).json()
        lt = lt_res['result']['_lt']

        params = {
            'lt': lt,
            'rememberMe': 'false',
            'dllt': '',
            'mobile': '',
            'username': self.username,
            'password': self.password,   # 明文提交（该校未做加密）
            'captcha': '',
        }

        # 2. 风控验证码
        if self.check_need_captcha():
            self.log('[IAP] 触发风控，需要输入验证码')
            img = self.get_captcha_image(lt)
            if captcha_prompt is not None:
                code = captcha_prompt(img)
            else:
                with open('captcha.png', 'wb') as f:
                    f.write(img)
                code = input('[IAP] 验证码图片已保存为 captcha.png，请输入验证码: ').strip()
            params['captcha'] = code

        # 3. 提交 doLogin，完整跟随重定向链（约 4 跳）签发 MOD_AUTH_CAS
        self.log('[IAP] 提交登录...')
        r = self._post_api('/iap/doLogin', data=params, allow_redirects=True, timeout=30)

        # 4. 结果判定：重定向链最终落在 portal 域且签发 MOD_AUTH_CAS（最终鉴权凭证）
        if '/portal/' in r.url or any(
                c.name == 'MOD_AUTH_CAS' for c in self.session.cookies):
            self.log('[IAP] 登录成功')
            return self.session.cookies

        self.count += 1
        try:
            data = r.json()
            code = data.get('resultCode', '')
        except Exception:
            code = ''
        if code == 'CAPTCHA_NOTMATCH':
            if self.count < 5:
                self.log('[IAP] 验证码错误，重试...')
                return self.login(captcha_prompt=captcha_prompt)
            raise Exception('验证码错误超过5次')
        elif code == 'FAIL_UPNOTMATCH':
            raise Exception('用户名或密码不匹配')
        else:
            raise Exception(f'登录失败，状态码: {code or r.status_code}，请检查账号/风控状态')