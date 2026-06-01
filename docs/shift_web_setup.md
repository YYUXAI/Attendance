# 班次 Web App（Telegram Mini App）本机部署说明

Telegram 要求 Web App 使用 **公网 HTTPS**。本机 Bot 的 HTTP 默认监听 `127.0.0.1:8787`，需用 **ngrok**（或自有域名反向代理）暴露到公网。

## 一、ngrok（已下载到本项目）

路径：`D:\考勤\Attendance_system\tools\ngrok\ngrok.exe`（v3）

首次使用：在 https://ngrok.com 注册，复制 **Authtoken**，执行一次：

```powershell
D:\考勤\Attendance_system\tools\ngrok\ngrok.exe config add-authtoken 你的token
```

或使用快捷脚本（需先 `cd` 到项目目录）：

```powershell
powershell -ExecutionPolicy Bypass -File D:\考勤\Attendance_system\scripts\start_ngrok.ps1
```

## 二、启动顺序（两个终端）

### 终端 1：考勤 Bot（含 HTTP 8787）

```powershell
cd D:\考勤\Attendance_system
python main.py
```

启动日志中应出现类似：`http_server: listening http://127.0.0.1:8787`

本地自检：

```powershell
curl http://127.0.0.1:8787/health
```

应返回 JSON：`{"ok":true,...}`

### 终端 2：ngrok 转发 8787

```powershell
D:\考勤\Attendance_system\tools\ngrok\ngrok.exe http 8787
```

复制 **Forwarding** 里的 HTTPS 地址，例如：

`https://a1b2c3d4.ngrok-free.app`

**不要**带末尾 `/`。

## 三、配置 .env

在 `D:\考勤\Attendance_system\.env` 中设置（把示例域名换成你的 ngrok 地址）：

```env
# HTTP 服务（与班次 Web 同端口）
DAILY_ATTENDANCE_REPORT_API_ENABLED=true
DAILY_ATTENDANCE_REPORT_API_HOST=127.0.0.1
DAILY_ATTENDANCE_REPORT_API_PORT=8787
DAILY_ATTENDANCE_REPORT_API_TOKEN=请设一串随机密钥

# 班次 Web App 公网地址（仅 HTTPS 根域名，无路径）
SHIFT_WEB_ENABLED=true
SHIFT_WEB_APP_PUBLIC_URL=https://a1b2c3d4.ngrok-free.app
SHIFT_WEB_TIMEZONE=Asia/Shanghai
```

修改 `.env` 后 **重启** `python main.py`。

浏览器可测（无需登录，仅测页面能否打开）：

`https://你的域名/shift-app/index.html?year_month=2026-05`

## 四、在 @BotFather 绑定域名（必做）

1. Telegram 打开 **@BotFather**
2. 发送 `/mybots` → 选择你的 Bot → **Bot Settings** → **Domain**
3. 填入 ngrok 的**主机名**（不要 `https://`），例如：`a1b2c3d4.ngrok-free.app`

若菜单里没有 Domain，可试：`/setdomain` → 选 Bot → 粘贴同上主机名。

未绑定域名时，点「班次」可能打不开 Web App。

## 五、在 Telegram 里验证

1. **私聊** Bot，发送 `/start`（管理员应看到底部「班次」）
2. 点底部 **班次** → 应弹出可编辑表格页
3. 修改后点 **上传** → 确认 → 提示保存成功

群内管理员也可点底部「班次」（群内无「导出」按钮）。

## 六、ngrok 出现 “You are about to visit” 拦截页

免费 ngrok 在**普通浏览器**第一次打开会要求点 **Visit Site**，属正常现象。

- **仅浏览器自测**：点一次 **Visit Site** 即可进入班次页。
- **Telegram 里要稳定打开**：建议改用 **cloudflared**（无此拦截页）：

```powershell
# 终端 2（替代 ngrok）
powershell -ExecutionPolicy Bypass -File D:\考勤\Attendance_system\scripts\start_cloudflared.ps1
```

把输出的 `https://xxxx.trycloudflare.com` 写入 `.env` 的 `SHIFT_WEB_APP_PUBLIC_URL`，并在 BotFather **Domain** 填 `xxxx.trycloudflare.com`，然后重启 Bot。

程序路径：`tools\cloudflared\cloudflared.exe`

## 七、签到「填入输入框」

1. 群内点底部 **签到**
2. Bot 会回复带 **填入输入框** 的消息
3. 点该按钮 → 草稿进入输入栏（可删 `@机器人`）→ 发送

## 常见问题

| 现象 | 处理 |
|------|------|
| 点班次提示未配置 URL | 检查 `SHIFT_WEB_APP_PUBLIC_URL` 是否 HTTPS、是否重启 Bot |
| Web 页空白 / 无法加载 | ngrok 是否在跑；`8787/health` 是否正常 |
| 打开 Web 提示无权限 | 确认你的 TG 账号在 `admin_list` 中 |
| ngrok 免费版 URL 每次变 | 每次重启 ngrok 后更新 `.env` 与 BotFather 域名 |
| 有自有域名 | Nginx/Caddy 反代到 `127.0.0.1:8787`，`SHIFT_WEB_APP_PUBLIC_URL` 填 `https://你的域名` |

## 生产环境建议

- 使用固定域名 + 正式 SSL，不要用经常变化的免费 ngrok（除非开发测试）。
- `DAILY_ATTENDANCE_REPORT_API_TOKEN` 勿提交到 Git。
- 仅管理员可访问班次 API（已用 Telegram `initData` + `admin_list` 校验）。
