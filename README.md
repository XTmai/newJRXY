# 今日校园查寝签到工具（示例大学适配版）

基于 [ZimoLoveShuang/auto-sign](https://github.com/ZimoLoveShuang/auto-sign) 改造，经 [CarltonHere/auto-cpdaily](https://github.com/CarltonHere/auto-cpdaily) → [TsangHaotian/JRXY-AutoSign-Reborn](https://github.com/TsangHaotian/JRXY-AutoSign-Reborn) 演进，本仓库针对 **示例大学** 做 CLOUD/IAP 适配。
架构：`core.py` 共享业务逻辑，`app.py` 桌面版，`main.py` 命令行版。

## 声明

本项目仅供学习交流，如作他用所承受的任何直接、间接法律责任一概与作者无关。

## 功能

- **IAP 账号密码登录**（joinType=CLOUD 学校），**会话持久化**（一次登录，7 天内免登录）
- 兼容扫码登录（NOTCLOUD 学校），按 joinType 自动分流
- 查看今日查寝任务
- 模拟手机 APP 签到（DES+AES 加密，真实 UA，固定校区定位，随机微偏模拟真实定位）
- 多校区支持
- 桌面版 + 命令行版 双入口

## 适配学校

- **示例大学** — 主校区（`example.campusphere.net`，CLOUD/IAP 账号密码登录）

> 若需适配其他学校，修改 `config.yml` 的 `schoolName`，程序会自动识别 joinType 并选择登录方式。

## 使用方法

### 安装依赖

```bash
pip install -r requirements.txt
```

项目已内置虚拟环境 `.venv`（Windows），也可直接用：

```bash
.venv\Scripts\python main.py --help
```

### 命令行版（推荐）

```bash
# 登录（CLOUD/IAP 学校：账号 + 密码）
python main.py login --user 学号 --password 密码

# 列出任务
python main.py list

# 签到（按序号或名称）
python main.py sign                    # 默认签第一个未签
python main.py sign --index 0          # 签第1个
python main.py sign --name "晚间"      # 按名称匹配
python main.py sign --photo a.jpg      # 带照片签到

# 静默模式（使用已保存会话，适合云端/定时任务）
python main.py --headless list
python main.py --headless sign --index 0 --photo a.jpg

# 查看登录状态
python main.py status
```

> 若学校类型为 NOTCLOUD（如新疆师大原版），`login` 会自动切换为扫码登录。

### 桌面版

```bash
python app.py
```

> 桌面版已适配双模式：CLOUD 学校显示账号密码表单，NOTCLOUD 学校显示扫码二维码，按 joinType 自动切换。

## 项目结构

```
├── core.py             # 业务核心（加密、登录分流、iOS first_v4 提交）
├── iap_login.py        # IAP 统一认证登录（RSA 密码加密）
├── app.py              # tkinter 桌面版
├── main.py             # 命令行版
├── config.yml          # 配置（学校、校区、密钥）
├── key_extract/        # gsk_client 领钥、脚本 脚本、逆向文档
├── .session_cookies.json  # 登录会话文件（自动生成，勿提交）
└── requirements.txt
```

## 已适配与验证

- ✅ joinType=CLOUD 识别，IAP 登录跑通（RSA-1024 密码加密 + 换 MOD_AUTH_CAS 票）
- ✅ 会话落盘与复用（CONVERSATION / CASTGC / MOD_AUTH_CAS）
- ✅ 任务列表接口连通
- ✅ **iOS first_v4 签到协议**（9.9.22）：bodyString=AES-128-CBC-PKCS7，key=interleave(`REDACTED`+服务器catSecret)，IV=原始字节 `01..09 01..07`；服务器实弹验证解密成功（见《02_协议数据与使用指南.md》）
- ✅ 校区坐标已配置：新校区 `0.0, 0.0`
- ⚠️ **设备授权风控**：提交进入业务层后返回"更换手机频繁/设备授权"（管理措施），需辅导员在辅导猫后台「手机授权管理」为本机授权，或真机正常使用一段时间自动解除

## 技术说明

| 项目 | 说明 |
|------|------|
| 登录方式 | CLOUD：`/iap/doLogin` RSA 加密密码（`{rsa}`+base64）+ form body + deviceId/fingerprintId 头；NOTCLOUD：CAS 扫码 |
| 签到协议 | iOS first_v4（`version=first_v4`, `calVersion=firstv`），AES-128-CBC-PKCS7 + interleave key + 真机指纹头 |
| 密钥派生 | `final_cat_secret`：本地常量 `REDACTED` + 服务器 `catSecret`（本校恒为 `REDACTED`）奇偶位交错 → `REDACTED` |
| APP 版本 | cpdaily/wisedu 9.9.22（iOS） |
| 定位方式 | 校区固定经纬度（围栏内，不微偏，避免越界） |
| 会话有效期 | 7 天 |

> 逆向过程原始记录见 `key_extract/` 与《01/02/03_*.md》文档。

## 项目演化史

- 源自 [ZimoLoveShuang/auto-sign](https://github.com/ZimoLoveShuang/auto-sign)（通用今日校园框架）
- 经 [CarltonHere/auto-cpdaily](https://github.com/CarltonHere/auto-cpdaily) 维护
- [TsangHaotian/JRXY-AutoSign-Reborn](https://github.com/TsangHaotian/JRXY-AutoSign-Reborn) 专攻新疆师大查寝：扫码登录、tkinter GUI、AES 9.9.20 密钥修复（PR #3）
- 本分支：改写为 **CLOUD/IAP 账号密码登录**，适配示例大学

## 许可证

MPL-2.0