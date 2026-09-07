"""
今日校园查寝签到工具 - tkinter桌面版
薄GUI层，业务逻辑委托给core.CpdailyClient
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import threading
import os
import json
import uuid
from datetime import datetime, timedelta
from PIL import Image, ImageTk

import requests

from core import CpdailyClient, BASE_UA

AUTO_CONFIG_FILE = 'auto_config.json'
AUTO_LOG_FILE = 'auto_sign.log'


# ==================== 主题色 ====================

COLOR_PRIMARY = '#2b5c8a'
COLOR_PRIMARY_LIGHT = '#4a8bc2'
COLOR_BG = '#f0f4f8'
COLOR_CARD = '#ffffff'
COLOR_TEXT = '#1a2332'
COLOR_TEXT_SECONDARY = '#6b7a8f'
COLOR_SUCCESS = '#27ae60'
COLOR_DANGER = '#e74c3c'
COLOR_WARNING = '#f39c12'
COLOR_BORDER = '#dce3ed'

FONT_TITLE = ('Microsoft YaHei', 14, 'bold')
FONT_NORMAL = ('Microsoft YaHei', 10)
FONT_SMALL = ('Microsoft YaHei', 9)
FONT_BOLD = ('Microsoft YaHei', 10, 'bold')


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f'今日校园查寝签到 v2.4')
        self.root.geometry(f'960x{min(1060, self.root.winfo_screenheight() - 40)}')
        self.root.minsize(860, 700)
        self.root.configure(bg=COLOR_BG)
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

        # 核心客户端
        self.client = CpdailyClient.from_config()
        self.client.on_log = self._core_log

        self.login_thread = None
        self.poll_stop = False
        self.signing = False
        self.photo_path = ''
        self.current_tasks = []
        self.user_info = {}  # 登录后存储用户信息
        self.log_messages = []

        # 自动签到状态
        self.auto_cfg = self._load_auto_config()
        self.auto_enabled = False
        self.auto_thread = None
        self.auto_stop = threading.Event()
        self.next_trigger = None      # datetime 下次触发点

        self._build_ui()
        self._init_school()

    # ==================== UI 构建 ====================

    def _build_header(self, parent):
        """顶部标题区"""
        header = tk.Frame(parent, bg=COLOR_PRIMARY, height=50)
        header.pack(fill='x')
        header.pack_propagate(False)

        tk.Label(header, text='🏫 今日校园查寝签到', fg='white', bg=COLOR_PRIMARY,
                 font=FONT_TITLE).pack(side='left', padx=20, pady=8)

    def _build_login_card(self, parent):
        """登录卡片（左二维码 + 右信息）"""
        card = tk.Frame(parent, bg=COLOR_CARD, highlightbackground=COLOR_BORDER,
                        highlightthickness=1, padx=15, pady=12)
        card.pack(fill='x', padx=12, pady=(12, 0))

        # 标题行
        tk.Label(card, text='🔐 登录认证', font=FONT_BOLD, bg=COLOR_CARD,
                 fg=COLOR_TEXT).pack(anchor='w')

        # 左右布局
        body = tk.Frame(card, bg=COLOR_CARD)
        body.pack(fill='x', pady=6)

        # 左侧：认证区（NOTCLOUD=二维码 / CLOUD=账号密码）
        left = tk.Frame(body, bg=COLOR_CARD)
        left.pack(side='left', fill='y')

        self.qr_label = tk.Label(left, bg=COLOR_CARD)
        self.qr_label.pack(pady=(10, 0))

        # CLOUD/IAP 账号密码表单
        self.iap_frame = tk.Frame(left, bg=COLOR_CARD)
        tk.Label(self.iap_frame, text='学号/工号', font=FONT_SMALL, bg=COLOR_CARD,
                 fg=COLOR_TEXT).pack(anchor='w')
        self.entry_user = tk.Entry(self.iap_frame, font=FONT_NORMAL, width=20)
        self.entry_user.pack(pady=(2, 6))
        tk.Label(self.iap_frame, text='密码', font=FONT_SMALL, bg=COLOR_CARD,
                 fg=COLOR_TEXT).pack(anchor='w')
        self.entry_pass = tk.Entry(self.iap_frame, font=FONT_NORMAL, width=20, show='*')
        self.entry_pass.pack(pady=(2, 8))
        self.entry_pass.bind('<Return>', lambda _e: self.start_login())

        self.btn_login = tk.Button(left, text='📱 扫码登录', font=FONT_NORMAL,
                                   bg=COLOR_PRIMARY, fg='white', relief='flat',
                                   activebackground=COLOR_PRIMARY_LIGHT,
                                   command=self.start_login, state='disabled',
                                   width=16, height=1)
        self.btn_login.pack(pady=(8, 2))
        self.btn_switch = tk.Button(left, text='🔄 切换账号', font=FONT_SMALL,
                                    bg='white', fg=COLOR_TEXT, relief='flat',
                                    highlightbackground=COLOR_BORDER,
                                    command=self.switch_account, state='disabled',
                                    width=16)
        self.btn_switch.pack()

        # 右侧：登录状态 + 信息
        right = tk.Frame(body, bg=COLOR_CARD, padx=15)
        right.pack(side='left', fill='both', expand=True)

        self.login_status_title = tk.Label(right, text='状态', font=FONT_BOLD,
                                           bg=COLOR_CARD, fg=COLOR_TEXT_SECONDARY,
                                           anchor='w')
        self.login_status_title.pack(fill='x')

        self.login_status = tk.StringVar(value='正在初始化...')
        tk.Label(right, textvariable=self.login_status, font=FONT_NORMAL,
                 bg=COLOR_CARD, fg=COLOR_PRIMARY, anchor='w',
                 wraplength=400).pack(fill='x', pady=(2, 8))

        # 用户信息（登录后显示）
        self.user_frame = tk.Frame(right, bg=COLOR_CARD)
        self.user_label = tk.Label(self.user_frame, bg=COLOR_CARD,
                                   font=FONT_NORMAL, fg=COLOR_TEXT,
                                   wraplength=400, justify='left')
        self.user_label.pack(anchor='w')
        self.session_label = tk.Label(self.user_frame, bg=COLOR_CARD,
                                      font=FONT_SMALL, fg=COLOR_TEXT_SECONDARY)
        self.session_label.pack(anchor='w', pady=(2, 0))

    def _build_config_card(self, parent):
        """配置卡片"""
        card = tk.Frame(parent, bg=COLOR_CARD, highlightbackground=COLOR_BORDER,
                        highlightthickness=1, padx=15, pady=10)
        card.pack(fill='x', padx=12, pady=(8, 0))

        tk.Label(card, text='⚙️ 签到配置', font=FONT_BOLD, bg=COLOR_CARD,
                 fg=COLOR_TEXT).pack(anchor='w')

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill='x', pady=4)

        tk.Label(row, text='签到校区', font=FONT_NORMAL, bg=COLOR_CARD,
                 fg=COLOR_TEXT).pack(side='left')
        self.campus_var = tk.StringVar(value=self.client.campus)
        campus_menu = ttk.Combobox(row, textvariable=self.campus_var,
                                   values=list(self.client.campuses.keys()),
                                   state='readonly', width=12, font=FONT_NORMAL)
        campus_menu.pack(side='left', padx=(8, 20))

        tk.Label(row, text='签到照片', font=FONT_NORMAL, bg=COLOR_CARD,
                 fg=COLOR_TEXT).pack(side='left')
        self.photo_label = tk.Label(row, text='未选择（非必选）', font=FONT_NORMAL,
                                    bg=COLOR_CARD, fg=COLOR_TEXT_SECONDARY)
        self.photo_label.pack(side='left', padx=(8, 4))
        ttk.Button(row, text='浏览', command=self._choose_photo, width=6).pack(side='left')

    def _build_auto_card(self, parent):
        """自动签到卡片：开关 + 参数 + 状态"""
        card = tk.Frame(parent, bg=COLOR_CARD, highlightbackground=COLOR_BORDER,
                        highlightthickness=1, padx=15, pady=10)
        card.pack(fill='x', padx=12, pady=(8, 0))

        title_row = tk.Frame(card, bg=COLOR_CARD)
        title_row.pack(fill='x')
        tk.Label(title_row, text='🤖 自动签到', font=FONT_BOLD, bg=COLOR_CARD,
                 fg=COLOR_TEXT).pack(side='left')

        self.btn_auto_toggle = tk.Button(title_row, text='▶ 开启自动签到', font=FONT_BOLD,
                                         bg=COLOR_SUCCESS, fg='white', relief='flat',
                                         command=self.toggle_auto, width=14)
        self.btn_auto_toggle.pack(side='right')

        self.auto_status = tk.StringVar(value='未开启')
        tk.Label(title_row, textvariable=self.auto_status, font=FONT_SMALL,
                 bg=COLOR_CARD, fg=COLOR_TEXT_SECONDARY).pack(side='right', padx=10)

        row1 = tk.Frame(card, bg=COLOR_CARD)
        row1.pack(fill='x', pady=(6, 2))
        tk.Label(row1, text='触发时刻', font=FONT_NORMAL, bg=COLOR_CARD,
                 fg=COLOR_TEXT).pack(side='left')
        self.entry_times = tk.Entry(row1, font=FONT_NORMAL, width=18)
        self.entry_times.pack(side='left', padx=(8, 20))
        self.entry_times.insert(0, ', '.join(self.auto_cfg.get('times', ['22:00'])))
        self.entry_times.bind('<FocusOut>', lambda _e: self._save_auto_settings())
        tk.Label(row1, text='重查间隔(分)', font=FONT_NORMAL, bg=COLOR_CARD,
                 fg=COLOR_TEXT).pack(side='left')
        self.entry_interval = tk.Entry(row1, font=FONT_NORMAL, width=4)
        self.entry_interval.pack(side='left', padx=(8, 20))
        self.entry_interval.insert(0, str(self.auto_cfg.get('retryIntervalMinutes', 5)))
        self.entry_interval.bind('<FocusOut>', lambda _e: self._save_auto_settings())
        tk.Label(row1, text='最大重查', font=FONT_NORMAL, bg=COLOR_CARD,
                 fg=COLOR_TEXT).pack(side='left')
        self.entry_maxretry = tk.Entry(row1, font=FONT_NORMAL, width=4)
        self.entry_maxretry.pack(side='left', padx=(8, 0))
        self.entry_maxretry.insert(0, str(self.auto_cfg.get('maxRetries', 12)))
        self.entry_maxretry.bind('<FocusOut>', lambda _e: self._save_auto_settings())

        row2 = tk.Frame(card, bg=COLOR_CARD)
        row2.pack(fill='x', pady=(2, 2))
        tk.Label(row2, text='照片池目录', font=FONT_NORMAL, bg=COLOR_CARD,
                 fg=COLOR_TEXT).pack(side='left')
        self.photo_dir_label = tk.Label(row2, text='未设置', font=FONT_NORMAL,
                                        bg=COLOR_CARD, fg=COLOR_TEXT_SECONDARY)
        self.photo_dir_label.pack(side='left', padx=(8, 4))
        ttk.Button(row2, text='浏览', command=self._choose_photo_dir, width=6).pack(side='left')
        self.photo_dir_count = tk.Label(row2, text='', font=FONT_SMALL,
                                        bg=COLOR_CARD, fg=COLOR_TEXT_SECONDARY)
        self.photo_dir_count.pack(side='left', padx=(8, 0))

        row3 = tk.Frame(card, bg=COLOR_CARD)
        row3.pack(fill='x', pady=(2, 0))
        self.remember_pwd_var = tk.BooleanVar(value=self.auto_cfg.get('rememberPassword', False))
        tk.Checkbutton(row3, text='记住密码（会话过期自动重登）', variable=self.remember_pwd_var,
                       font=FONT_SMALL, bg=COLOR_CARD, fg=COLOR_TEXT,
                       command=self._save_auto_settings).pack(side='left')
        tk.Label(row3, text='（凭据保存在本机 auto_config.json）', font=FONT_SMALL,
                 bg=COLOR_CARD, fg=COLOR_TEXT_SECONDARY).pack(side='left', padx=6)

        self._update_photo_dir_count()

    def _build_task_card(self, parent):
        """任务卡片"""
        card = tk.Frame(parent, bg=COLOR_CARD, highlightbackground=COLOR_BORDER,
                        highlightthickness=1, padx=15, pady=10)
        card.pack(fill='both', expand=True, padx=12, pady=(8, 0))

        # 标题行 + 按钮（按钮放在右侧）
        title_row = tk.Frame(card, bg=COLOR_CARD)
        title_row.pack(fill='x')
        tk.Label(title_row, text='📋 查寝任务', font=FONT_BOLD, bg=COLOR_CARD,
                 fg=COLOR_TEXT).pack(side='left')

        self.task_count_label = tk.Label(title_row, text='', font=FONT_SMALL,
                                         bg=COLOR_CARD, fg=COLOR_TEXT_SECONDARY)
        self.task_count_label.pack(side='left', padx=8)

        self.btn_sign = tk.Button(title_row, text='✅ 签到选中', font=FONT_BOLD,
                                  bg=COLOR_SUCCESS, fg='white', relief='flat',
                                  command=self.start_sign, state='disabled',
                                  width=12)
        self.btn_sign.pack(side='right', padx=(4, 0))

        self.btn_refresh = tk.Button(title_row, text='🔄 刷新', font=FONT_NORMAL,
                                     bg='white', fg=COLOR_TEXT, relief='flat',
                                     highlightbackground=COLOR_BORDER,
                                     command=self.refresh_tasks, state='disabled',
                                     width=8)
        self.btn_refresh.pack(side='right')

        # 表格
        columns = ('status', 'sender', 'time')
        self.task_tree = ttk.Treeview(card, columns=columns, show='tree', height=3,
                                      selectmode='browse')
        self.task_tree.heading('#0', text='任务名称')
        self.task_tree.heading('status', text='状态')
        self.task_tree.heading('sender', text='发布人')
        self.task_tree.heading('time', text='签到时段')
        self.task_tree.column('#0', width=200, minwidth=160)
        self.task_tree.column('status', width=50, minwidth=45, anchor='center')
        self.task_tree.column('sender', width=160, minwidth=120)
        self.task_tree.column('time', width=180, minwidth=150)
        self.task_tree.bind('<<TreeviewSelect>>', self._on_task_select)

        scrollbar = ttk.Scrollbar(card, orient='vertical', command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=scrollbar.set)
        self.task_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        self.sign_info_label = tk.Label(card, text='', font=FONT_SMALL,
                                        bg=COLOR_CARD, fg=COLOR_TEXT_SECONDARY)
        self.sign_info_label.pack(anchor='w', pady=(4, 0))

    def _build_log_card(self, parent):
        """日志卡片"""
        card = tk.Frame(parent, bg=COLOR_CARD, highlightbackground=COLOR_BORDER,
                        highlightthickness=1, padx=15, pady=8)
        card.pack(fill='both', padx=12, pady=(8, 12))

        tk.Label(card, text='📝 运行日志', font=FONT_BOLD, bg=COLOR_CARD,
                 fg=COLOR_TEXT).pack(anchor='w')

        self.log_text = tk.Text(card, height=8, font=('Consolas', 9),
                                bg='#f7f9fc', fg=COLOR_TEXT, relief='flat',
                                state='disabled', wrap='word')
        scrollbar = ttk.Scrollbar(card, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side='left', fill='both', expand=True, pady=(4, 0))
        scrollbar.pack(side='right', fill='y', pady=(4, 0))

    def _build_footer(self, parent):
        """底部信息"""
        footer = tk.Frame(parent, bg=COLOR_BG, height=24)
        footer.pack(fill='x')
        footer.pack_propagate(False)
        tk.Label(footer, text=f'v2.4 | {self.client.school_name} | 基于 MPL-2.0 开源',
                 font=('Microsoft YaHei', 8), bg=COLOR_BG,
                 fg=COLOR_TEXT_SECONDARY).pack(pady=3)

    def _build_ui(self):
        # 内容区总高超过屏幕，用 Canvas 容器支持滚轮滚动
        canvas = tk.Canvas(self.root, bg=COLOR_BG, highlightthickness=0)
        vbar = ttk.Scrollbar(self.root, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        canvas.pack(side='left', fill='both', expand=True)
        vbar.pack(side='right', fill='y')

        container = tk.Frame(canvas, bg=COLOR_BG)
        win = canvas.create_window((0, 0), window=container, anchor='nw')
        container.bind('<Configure>',
                       lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',
                    lambda _e: canvas.itemconfigure(win, width=canvas.winfo_width()))

        def _on_mousewheel(e):
            # Text/Treeview/Combobox 自己处理滚轮
            if e.widget.winfo_class() not in ('Text', 'Treeview', 'TCombobox'):
                canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        canvas.bind_all('<MouseWheel>', _on_mousewheel, add='+')

        self._build_header(container)
        self._build_login_card(container)
        self._build_config_card(container)
        self._build_auto_card(container)
        self._build_task_card(container)
        self._build_log_card(container)
        self._build_footer(container)

    # ==================== 工具方法 ====================

    def _core_log(self, msg):
        """来自core的日志"""
        now = datetime.now().strftime('%H:%M:%S')
        self.log_messages.append((now, msg))

    def log(self, msg):
        """写入日志区"""
        now = datetime.now().strftime('%H:%M:%S')
        self.log_messages.append((now, msg))
        def _append():
            self.log_text.configure(state='normal')
            self.log_text.insert('end', f'[{now}] {msg}\n')
            self.log_text.see('end')
            self.log_text.configure(state='disabled')
        self.root.after(0, _append)

    def set_status(self, text, is_ok=False, is_err=False):
        """更新登录状态"""
        self.root.after(0, lambda: self.login_status.set(text))

    def _apply_login_mode(self):
        """按 joinType 切换登录方式 UI（CLOUD=账号密码 / 其他=扫码）"""
        if self.client.join_type == 'CLOUD':
            self.qr_label.pack_forget()
            self.iap_frame.pack(pady=(10, 0))
            self.btn_login.configure(text='🔑 账号密码登录')
        else:
            self.iap_frame.pack_forget()
            self.qr_label.pack(pady=(10, 0))
            self.btn_login.configure(text='📱 扫码登录')

    def show_qr(self, path):
        try:
            img = Image.open(path).resize((180, 180))
            # 加白边框
            bordered = Image.new('RGB', (190, 190), 'white')
            bordered.paste(img, (5, 5))
            photo = ImageTk.PhotoImage(bordered)
            self.qr_label.configure(image=photo)
            self.qr_label.image = photo
        except:
            pass

    def clear_qr(self):
        self.qr_label.configure(image='')

    def update_user_info(self):
        """登录后更新用户信息（显示学校、校区、会话时间）"""
        def _update():
            school = self.client.school_name
            campus = self.client.campus
            now = datetime.now().strftime('%Y-%m-%d %H:%M')

            lines = [
                f'🏫 {school}',
                f'📍 {campus}',
            ]
            self.user_label.configure(text='  |  '.join(lines))
            self.session_label.configure(text=f'🕐 会话时间: {now}  ·  状态: 有效')

            if not self.user_frame.winfo_ismapped():
                self.user_frame.pack(fill='x', pady=(4, 0))
        self.root.after(0, _update)

    def update_task_count(self, unsigned, signed):
        def _update():
            total = unsigned + signed
            if total == 0:
                self.task_count_label.configure(text='(暂无任务)')
            else:
                self.task_count_label.configure(
                    text=f'(未签 {unsigned} / 已签 {signed} / 共 {total})')
        self.root.after(0, _update)

    def _choose_photo(self):
        path = filedialog.askopenfilename(title='选择签到照片',
                                          filetypes=[('图片', '*.jpg *.jpeg *.png')])
        if path:
            self.photo_path = path
            self.photo_label.configure(text=os.path.basename(path)[:16],
                                       fg=COLOR_TEXT)

    def _on_task_select(self, _event):
        sel = self.task_tree.selection()
        if sel:
            item = self.task_tree.item(sel[0])
            vals = item['values']
            if vals and vals[0] == '❌':
                self.btn_sign.configure(state='normal')
                self.sign_info_label.configure(text='')
            else:
                self.btn_sign.configure(state='disabled')
                if vals:
                    self.sign_info_label.configure(text='已签到，无需重复')
        else:
            self.btn_sign.configure(state='disabled')
            self.sign_info_label.configure(text='')

    # ==================== 自动签到 ====================

    def _load_auto_config(self):
        defaults = {'times': ['22:00'], 'retryIntervalMinutes': 5,
                    'maxRetries': 12, 'photoDir': '', 'rememberPassword': False,
                    'user': '', 'password': '', 'pushplusToken': ''}
        try:
            if os.path.exists(AUTO_CONFIG_FILE):
                with open(AUTO_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    defaults.update(json.load(f))
        except Exception:
            pass
        return defaults

    def _save_auto_config(self):
        try:
            with open(AUTO_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.auto_cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f'保存自动签到配置失败: {e}')

    def _collect_auto_settings(self):
        """从 UI 读取当前设置并入 auto_cfg，返回 (times列表, 错误信息)"""
        cfg = self.auto_cfg
        try:
            cfg['retryIntervalMinutes'] = max(1, int(self.entry_interval.get() or 5))
        except ValueError:
            cfg['retryIntervalMinutes'] = 5
        try:
            cfg['maxRetries'] = max(1, int(self.entry_maxretry.get() or 12))
        except ValueError:
            cfg['maxRetries'] = 12
        cfg['rememberPassword'] = bool(self.remember_pwd_var.get())
        if cfg['rememberPassword']:
            cfg['user'] = self.entry_user.get().strip()
            cfg['password'] = self.entry_pass.get()
        else:
            cfg['user'] = ''
            cfg['password'] = ''

        times, errors = [], []
        for raw in self.entry_times.get().replace('，', ',').split(','):
            raw = raw.strip().replace('：', ':')
            if not raw:
                continue
            try:
                h, m = raw.split(':')
                if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                    raise ValueError
                times.append(f'{int(h):02d}:{int(m):02d}')
            except ValueError:
                errors.append(raw)
        cfg['times'] = times
        self._save_auto_config()
        return times, errors

    def _save_auto_settings(self):
        self._collect_auto_settings()

    def _choose_photo_dir(self):
        path = filedialog.askdirectory(title='选择照片池目录（自动签到随机选图）')
        if path:
            self.auto_cfg['photoDir'] = path
            self.photo_dir_label.configure(text=os.path.basename(path) or path,
                                           fg=COLOR_TEXT)
            self._update_photo_dir_count()
            self._save_auto_config()

    def _update_photo_dir_count(self):
        d = self.auto_cfg.get('photoDir', '')
        if d and os.path.isdir(d):
            exts = ('.jpg', '.jpeg', '.png')
            n = len([f for f in os.listdir(d) if f.lower().endswith(exts)])
            self.photo_dir_label.configure(text=os.path.basename(d) or d, fg=COLOR_TEXT)
            self.photo_dir_count.configure(text=f'共 {n} 张' if n else '(空!)')
        else:
            self.photo_dir_label.configure(text='未设置', fg=COLOR_TEXT_SECONDARY)
            self.photo_dir_count.configure(text='')

    def _alog(self, msg):
        """自动签到日志：GUI 日志区 + 文件双写"""
        self.log(msg)
        try:
            with open(AUTO_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {msg}\n')
        except Exception:
            pass

    def _push_notify(self, title, content):
        """pushplus 微信推送，token 为空则跳过"""
        token = self.auto_cfg.get('pushplusToken', '')
        if not token:
            return
        try:
            requests.post('https://www.pushplus.plus/send',
                          json={'token': token, 'title': title,
                                'content': content, 'template': 'txt'},
                          timeout=10)
        except Exception:
            pass

    @staticmethod
    def _parse_hhmm(s):
        h, m = s.split(':')
        return int(h), int(m)

    def _compute_next_trigger(self, times, after=None):
        """times 里的下一个触发点（今天没过 -> 明天最早），返回 datetime"""
        base = after or datetime.now()
        candidates = []
        for t in times:
            h, m = self._parse_hhmm(t)
            cand = base.replace(hour=h, minute=m, second=0, microsecond=0)
            if cand <= base:
                cand += timedelta(days=1)
            candidates.append(cand)
        return min(candidates)

    def toggle_auto(self):
        if self.auto_enabled:
            self._stop_auto()
        else:
            self._start_auto()

    def _start_auto(self):
        if not self.client.logged_in:
            messagebox.showwarning('提示', '请先登录，再开启自动签到')
            return
        times, errors = self._collect_auto_settings()
        if not times:
            messagebox.showwarning('提示', '请填写有效的触发时刻，如 22:00（多个用逗号分隔）')
            return
        if errors:
            self.log(f'忽略无效时刻: {", ".join(errors)}')
        if not messagebox.askyesno('开启自动签到',
                                   f'到点将自动完成查寝签到。\n'
                                   f'触发时刻: {", ".join(times)}\n'
                                   f'照片池: {self.auto_cfg.get("photoDir") or "(未设置)"}\n'
                                   f'确定开启吗？'):
            return
        self.auto_enabled = True
        self.auto_stop.clear()
        self.next_trigger = self._compute_next_trigger(times)
        self._save_auto_config()
        self.btn_auto_toggle.configure(text='⏸ 关闭自动签到', bg=COLOR_DANGER)
        self.auto_thread = threading.Thread(target=self._auto_scheduler_loop, daemon=True)
        self.auto_thread.start()
        self.root.after(1000, self._auto_ticker)
        self._alog(f'✅ 自动签到已开启，下次触发: {self.next_trigger.strftime("%m-%d %H:%M")}')

    def _stop_auto(self):
        self.auto_enabled = False
        self.auto_stop.set()
        self.next_trigger = None
        self._save_auto_config()
        self.btn_auto_toggle.configure(text='▶ 开启自动签到', bg=COLOR_SUCCESS)
        self.auto_status.set('未开启')
        self._alog('自动签到已关闭')

    def _auto_ticker(self):
        """每秒更新状态行倒计时"""
        if not self.auto_enabled:
            return
        if self.next_trigger:
            remain = self.next_trigger - datetime.now()
            total = max(0, int(remain.total_seconds()))
            hh, rem = divmod(total, 3600)
            mm, ss = divmod(rem, 60)
            self.auto_status.set(
                f'已开启 · 下次 {self.next_trigger.strftime("%H:%M")}（剩 {hh:02d}:{mm:02d}:{ss:02d}）')
        self.root.after(1000, self._auto_ticker)

    def _auto_scheduler_loop(self):
        """调度线程：tick 等到触发点（含睡眠唤醒补触发），到点跑签到流程"""
        while not self.auto_stop.is_set():
            if datetime.now() >= self.next_trigger:
                try:
                    self._auto_sign_flow()
                except Exception as e:
                    self._alog(f'❌ 自动签到异常: {e}')
                    self._push_notify('查寝自动签到异常', str(e))
                if self.auto_stop.is_set():
                    break
                self.next_trigger = self._compute_next_trigger(self.auto_cfg['times'])
                self._alog(f'下次触发: {self.next_trigger.strftime("%m-%d %H:%M")}')
            self.auto_stop.wait(timeout=1)

    def _wait_manual_signing(self):
        """手动签到进行中则等待，最多5分钟，返回是否可继续"""
        for _ in range(10):
            if not self.signing:
                return True
            self._alog('手动签到进行中，等待30秒...')
            if self.auto_stop.wait(timeout=30):
                return False
        return not self.signing

    def _auto_relogin(self):
        """会话失效时用记住的凭据自动重登，返回是否成功"""
        user = self.auto_cfg.get('user', '')
        pwd = self.auto_cfg.get('password', '')
        if not user or not pwd:
            self._alog('❌ 会话已失效，且未勾选"记住密码"，无法自动重登')
            return False
        try:
            self._alog(f'会话失效，正在自动重登: {user}')
            if self.client.join_type == 'CLOUD':
                self.client.login_iap(user, pwd, captcha_provider=self._ask_captcha)
            else:
                self._alog('❌ 扫码登录学校无法自动重登，请手动扫码')
                return False
            self._alog('✅ 自动重登成功')
            self.set_status('✅ 自动重登成功', is_ok=True)
            self.root.after(0, lambda: self.btn_switch.configure(state='normal'))
            return True
        except Exception as e:
            self._alog(f'❌ 自动重登失败: {e}')
            return False

    def _auto_sign_flow(self):
        """到点触发的完整签到流程（调度线程中执行）"""
        if not self._wait_manual_signing():
            return
        self.signing = True
        try:
            self._alog('⏰ 触发自动签到')
            self.set_status('自动签到中...')
            self.root.after(0, lambda: self.auto_status.set('自动签到执行中...'))

            # 1. 会话校验 + 自动重登
            if not self.client.is_session_valid():
                if not self._auto_relogin():
                    self._push_notify('查寝自动签到失败', '会话失效且自动重登失败，请打开程序手动处理')
                    return

            # 2. 轮询任务（防任务晚发布）
            interval = self.auto_cfg['retryIntervalMinutes']
            max_retries = self.auto_cfg['maxRetries']
            result = None
            for attempt in range(max_retries + 1):
                try:
                    result = self.client.list_tasks()
                    break
                except Exception as e:
                    self._alog(f'拉取任务失败({attempt + 1}/{max_retries + 1}): {e}')
                    if attempt < max_retries and self.auto_stop.wait(timeout=interval * 60):
                        return
            if result is None:
                self._push_notify('查寝自动签到失败', '多次拉取任务失败，请检查网络')
                return

            unsigned = result['unsigned']
            if not unsigned:
                self._alog(f'今日暂无未签任务（已重查 {max_retries + 1} 次），本次结束')
                return

            # 3. 逐个签到（照片池选图）
            photo_dir = self.auto_cfg.get('photoDir', '')
            campus = self.campus_var.get()
            ok, fail = 0, []
            for i, t in enumerate(unsigned):
                self._alog(f'正在签: {t["taskName"]}')
                try:
                    r = self.client.sign_task(t, campus=campus, photo_dir=photo_dir)
                    if r['success']:
                        ok += 1
                        self._alog(f'✅ {t["taskName"]} 签到成功')
                    else:
                        fail.append(f'{t["taskName"]}: {r["message"]}')
                        self._alog(f'❌ {t["taskName"]} 签到失败: {r["message"]}')
                except Exception as e:
                    fail.append(f'{t["taskName"]}: {e}')
                    self._alog(f'❌ {t["taskName"]} 异常: {e}')
                if i != len(unsigned) - 1:
                    self.auto_stop.wait(timeout=3)

            # 4. 复核 + 收尾
            try:
                result = self.client.list_tasks()
                remain = len(result['unsigned'])
            except Exception:
                remain = -1
            self.root.after(0, self.refresh_tasks)

            summary = f'成功 {ok} 个，失败 {len(fail)} 个' + (
                f'，复核剩余未签 {remain} 个' if remain > 0 else '')
            self._alog(f'自动签到完成: {summary}')
            if fail:
                self._push_notify('查寝自动签到部分失败',
                                  f'成功 {ok}，失败:\n' + '\n'.join(fail))
            elif ok:
                self._push_notify('查寝自动签到成功', f'已自动完成 {ok} 个查寝任务')
        finally:
            self.signing = False

    def _on_close(self):
        if self.auto_enabled:
            self._collect_auto_settings()
            self._stop_auto()
        else:
            self._collect_auto_settings()
        self.root.destroy()

    # ==================== 学校初始化 ====================

    def _init_school(self):
        threading.Thread(target=self._do_init_school, daemon=True).start()

    def _do_init_school(self):
        try:
            self.log('正在获取学校信息...')
            self.client.init_school()
            self.log(f'学校: {self.client.school_name}')
            self.log(f'域名: {self.client.campus_host}')
            self.set_status('准备就绪，请登录')
            self.root.after(0, lambda: self.btn_login.configure(state='normal'))
            self.root.after(0, self._apply_login_mode)
            if self.client.logged_in:
                self.set_status('✅ 已登录（恢复会话）', is_ok=True)
                self.root.after(0, lambda: self.btn_switch.configure(state='normal'))
                self.root.after(0, lambda: self.btn_refresh.configure(state='normal'))
                self.refresh_tasks()
        except Exception as e:
            self.log(f'初始化失败: {e}')
            self.set_status('初始化失败', is_err=True)

    def switch_account(self):
        """切换账号：清除会话 -> 重新扫码"""
        if self.signing:
            return
        if not messagebox.askyesno('切换账号', '确定切换账号吗？\n当前登录会话将被清除。'):
            return
        self.client._clear_session()
        self.client.logged_in = False
        self.client.session = requests.session()
        self.client.session.headers = {'User-Agent': BASE_UA}
        # 设备ID固定为真机值，避免触发"更换手机频繁"风控
        self.client.device_id = IOS_DEVICE_ID
        self.client.user_id = None

        # 恢复UI状态
        self.current_tasks = []
        self.root.after(0, lambda: self.task_tree.delete(*self.task_tree.get_children()))
        self.root.after(0, lambda: self.task_count_label.configure(text=''))
        self.root.after(0, lambda: self.btn_refresh.configure(state='disabled'))
        self.root.after(0, lambda: self.btn_switch.configure(state='disabled'))
        self.root.after(0, lambda: self.btn_login.configure(state='normal'))
        self.root.after(0, self._apply_login_mode)
        self.root.after(0, self.clear_qr)
        self.set_status('会话已清除，请重新登录')
        self.log('已清除登录会话，请重新登录')

    # ==================== 登录（扫码 / IAP 分流） ====================

    def start_login(self):
        if self.login_thread and self.login_thread.is_alive():
            return
        if self.client.join_type == 'CLOUD':
            self._start_iap_login()
        else:
            self._start_qr_login()

    # -------- IAP 账号密码登录（CLOUD 学校） --------

    def _start_iap_login(self):
        user = self.entry_user.get().strip()
        pwd = self.entry_pass.get()
        if not user or not pwd:
            messagebox.showwarning('提示', '请输入学号/工号和密码')
            return
        self.btn_login.configure(state='disabled', text='登录中...')
        self.login_thread = threading.Thread(
            target=self._do_iap_login, args=(user, pwd), daemon=True)
        self.login_thread.start()

    def _ask_captcha(self, img_bytes):
        """验证码输入回调（在登录后台线程中调用，弹窗切回主线程）"""
        import threading as _t
        with open('captcha.png', 'wb') as f:
            f.write(img_bytes)
        result, event = {}, _t.Event()

        def _ask():
            code = simpledialog.askstring(
                '验证码', '验证码图片已保存到项目目录 captcha.png\n'
                '请打开查看后输入验证码:', parent=self.root)
            result['code'] = code or ''
            event.set()

        self.root.after(0, _ask)
        event.wait(timeout=120)
        return result['code'].strip()

    def _do_iap_login(self, user, pwd):
        try:
            self.set_status('正在登录...')
            self.log(f'使用 IAP 账号密码登录: {user}')
            self.client.login_iap(user, pwd, captcha_provider=self._ask_captcha)
            self.set_status('✅ 登录成功', is_ok=True)
            self.log('✅ 登录成功!')
            self.root.after(0, lambda: self.btn_login.configure(
                state='disabled', text='✅ 已登录'))
            self.root.after(0, lambda: self.btn_switch.configure(state='normal'))
            self.root.after(0, lambda: self.btn_refresh.configure(state='normal'))
            self.refresh_tasks()
        except Exception as e:
            self.log(f'登录失败: {e}')
            self.set_status('登录失败', is_err=True)
            self.root.after(0, lambda: self.btn_login.configure(
                state='normal', text='🔑 账号密码登录'))

    # -------- 扫码登录（NOTCLOUD 学校） --------

    def _start_qr_login(self):
        self.btn_login.configure(state='disabled', text='登录中...')
        self.login_thread = threading.Thread(target=self._do_login, daemon=True)
        self.login_thread.start()

    def _do_login(self):
        try:
            self.log('正在获取二维码...')
            uuid, img_bytes = self.client.get_qr_image()
            self.log('二维码已生成，请用今日校园APP扫描')
            self.set_status('等待扫码...')

            qr_path = 'qrcode_login.png'
            with open(qr_path, 'wb') as f:
                f.write(img_bytes)
            self.root.after(0, lambda: self.show_qr(qr_path))

            def on_status(msg):
                self.set_status(msg)
                self.log(msg)

            success = self.client.poll_qr_login(uuid, on_status=on_status)

            if success:
                self.set_status('✅ 登录成功', is_ok=True)
                self.root.after(0, self.clear_qr)
                self.root.after(0, lambda: self.btn_login.configure(
                    state='disabled', text='✅ 已登录'))
                self.root.after(0, lambda: self.btn_switch.configure(state='normal'))
                self.root.after(0, lambda: self.btn_refresh.configure(state='normal'))
                self.refresh_tasks()
            else:
                self.set_status('扫码超时', is_err=True)
                self.root.after(0, self.clear_qr)
                self.root.after(0, lambda: self.btn_login.configure(
                    state='normal', text='📱 扫码登录'))
                self.root.after(0, lambda: self.btn_switch.configure(state='disabled'))
        except Exception as e:
            self.log(f'登录异常: {e}')
            self.set_status('登录失败', is_err=True)
            self.root.after(0, self.clear_qr)
            self.root.after(0, lambda: self.btn_login.configure(
                state='normal', text='📱 扫码登录'))

    # ==================== 刷新任务 ====================

    def refresh_tasks(self):
        self.btn_refresh.configure(state='disabled', text='刷新中...')
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        try:
            self.log('正在获取查寝任务...')
            result = self.client.list_tasks()
            self.current_tasks = result['all']
            unsigned = result['unsigned']
            signed = result['signed']

            self.update_task_count(len(unsigned), len(signed))
            self.update_user_info()

            def _update():
                self.task_tree.delete(*self.task_tree.get_children())
                for t in unsigned:
                    sender = t.get('senderUserName', '')
                    tr = f"{t.get('singleTaskBeginTime','')}-{t.get('singleTaskEndTime','')}"
                    self.task_tree.insert('', 'end', text=t['taskName'],
                                          values=('❌', sender, tr))
                for t in signed:
                    sender = t.get('senderUserName', '')
                    tr = f"{t.get('singleTaskBeginTime','')}-{t.get('singleTaskEndTime','')}"
                    self.task_tree.insert('', 'end', text=t['taskName'],
                                          values=('✅', sender, tr))
                if not result['all']:
                    self.task_tree.insert('', 'end', text='暂无查寝任务',
                                          values=('', '', ''))

            self.root.after(0, _update)
            self.log(f'今日: 未签到{len(unsigned)}个, 已签到{len(signed)}个')
        except Exception as e:
            self.log(f'获取任务失败: {e}')
        finally:
            self.root.after(0, lambda: self.btn_refresh.configure(
                state='normal', text='🔄 刷新'))

    # ==================== 签到 ====================

    def start_sign(self):
        if self.signing:
            return
        sel = self.task_tree.selection()
        if not sel:
            messagebox.showwarning('提示', '请先选择一个未签到任务')
            return
        item = self.task_tree.item(sel[0])
        vals = item['values']
        if not vals or vals[0] != '❌':
            messagebox.showwarning('提示', '该任务已签到')
            return

        task_name = item['text']
        task = None
        for t in self.current_tasks:
            if t['taskName'] == task_name:
                task = t
                break
        if not task:
            messagebox.showerror('错误', '未找到任务数据，请刷新')
            return

        if not messagebox.askyesno('确认签到', f'确定签到「{task_name}」吗？\n'
                                   f'校区: {self.campus_var.get()}'):
            return

        self.signing = True
        self.btn_sign.configure(state='disabled', text='签到中...')
        self.sign_info_label.configure(text='正在提交...', fg=COLOR_WARNING)
        threading.Thread(target=self._do_sign, args=(task,), daemon=True).start()

    def _do_sign(self, task):
        try:
            campus = self.campus_var.get()
            result = self.client.sign_task(task, campus=campus, photo_path=self.photo_path)
            if result['success']:
                self.set_status('✅ 签到成功', is_ok=True)
                self.log('✅ 签到成功!')
                self.root.after(0, lambda: messagebox.showinfo('成功', '签到成功!'))
                self.refresh_tasks()
            else:
                self.set_status('签到失败', is_err=True)
                self.log(f'❌ 签到失败: {result["message"]}')
                self.root.after(0, lambda: messagebox.showerror(
                    '失败', f'签到失败: {result["message"]}'))
        except Exception as e:
            self.log(f'签到出错: {e}')
            self.set_status('签到出错', is_err=True)
            self.root.after(0, lambda: messagebox.showerror('错误', f'签到出错: {e}'))
        finally:
            self.signing = False
            self.root.after(0, lambda: self.btn_sign.configure(
                state='normal', text='✅ 签到选中'))
            self.root.after(0, lambda: self.sign_info_label.configure(text=''))

    # ==================== 启动 ====================

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    app = App()
    app.run()
