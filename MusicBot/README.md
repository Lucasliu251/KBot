# KBot Music Console

Vue 3 + TypeScript + Vite 控制台，Python/Flask 提供 KOOK 与网易云兼容 API。

## 首次配置

```bash
cp .env.example .env
```

编辑 `.env`，至少填写：

```dotenv
BOT_TOKEN=你的_KOOK_机器人_Token
FFMPEG_PATH=/usr/bin/ffmpeg
FFPROBE_PATH=/usr/bin/ffprobe
```

机器人需要先被邀请进 KOOK 服务器，并拥有查看、加入目标语音频道的权限。服务器和语音频道会自动出现在网页选择器中，不需要把 ID 写进源码。

## 本地开发

```bash
npm install
npm run dev
```

`npm run dev` 会同时启动 Flask API（8004）与 Vite（5173）。只想查看界面预览时可运行：

```bash
npm run dev:web
```

## 频道地址

- `/Music`：打开频道选择器。
- `/Music/<频道ID>`：直接打开指定语音频道的控制台。

生产部署前运行 `npm run build`，Flask 会从 `static/music-console` 加载构建产物。
