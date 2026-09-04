#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整签到流程: init_school -> IAP 密码登录 -> 拉任务 -> iOS v4 协议签到
用法: python run_once.py [学号 密码]
"""
import sys
import json
import os

import urllib3
urllib3.disable_warnings()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import CpdailyClient


def input_captcha(img_bytes):
    """CLI 验证码回调：保存图片并让用户输入"""
    with open('captcha.png', 'wb') as f:
        f.write(img_bytes)
    return input('[IAP] 验证码图片已保存 captcha.png，请输入验证码: ').strip()


USER = sys.argv[1] if len(sys.argv) > 1 else '2024000000'
PWD = sys.argv[2] if len(sys.argv) > 2 else None
if not PWD:
    import getpass
    PWD = getpass.getpass('密码: ')

cli = CpdailyClient(school_name='示例大学', campus='新校区',
                    cookie_file='.session_cookies.json')
cli.on_log = lambda m: print('[LOG]', m)

print('====== 1. 初始化学校信息 ======')
cli.init_school()

print('====== 2. IAP 密码登录 ======')
if not cli.logged_in:
    cli._clear_session()
    ok = cli.login_iap(USER, PWD, captcha_provider=input_captcha)
    print('登录结果:', ok)
    if not ok:
        print('!!! 登录失败，终止')
        sys.exit(1)
else:
    print('已恢复已有会话')
print('cookies:', [c.name for c in cli.session.cookies])

print('====== 3. 拉取今日任务 ======')
tasks = cli.list_tasks()
unsigned, signed = tasks['unsigned'], tasks['signed']
print(f"未签任务 {len(unsigned)} 个, 已签 {len(signed)} 个")
for t in unsigned:
    print('  -', json.dumps({k: t.get(k) for k in
          ('signInstanceWid', 'signWid', 'taskName', 'className', 'beginTime', 'endTime', 'isPhoto')},
          ensure_ascii=False))
for t in signed:
    print('  [已签]', t.get('taskName'), t.get('beginTime'), '-', t.get('endTime'))

if not unsigned:
    print('>>> 今日暂无未签任务（可等任务发布后重跑）')
    sys.exit(0)

print('====== 4. 逐个签到（iOS first_v4 协议） ======')
results = []
for t in unsigned:
    r = cli.sign_task(t)
    results.append({'task': t.get('taskName'), 'result': r})
    print('=>', t.get('taskName'), '->', r)

print('====== 汇总 ======')
print(json.dumps(results, ensure_ascii=False, indent=2))