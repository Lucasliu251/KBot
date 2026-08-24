# KBot Music Console

Vue 3 + TypeScript + Vite 控制台，Python/Flask 提供 KOOK 与网易云兼容 API。

搜索菜单支持网易云/QQ音乐双音源，默认仍为网易云。QQ音乐通过内置的
[L-1124/QQMusicApi](https://github.com/L-1124/QQMusicApi) 0.7.2 适配，第一次
使用时在 Banner 右侧齿轮“音乐服务后台”中使用 QQ 或微信扫码登录会员账号。

## 首次配置

```bash
cp .env.example .env
```

编辑 `.env`，至少填写：

```dotenv
MUSIC_BOT_TOKEN=你的_MusicBot_KOOK机器人_Token
MUSIC_SETTINGS_TOKEN=单独生成的随机管理密钥
FFMPEG_PATH=/usr/bin/ffmpeg
FFPROBE_PATH=/usr/bin/ffprobe
MUSIC_PRELOAD_SECONDS=600
MUSIC_STREAM_BUFFER_SECONDS=45
MUSIC_STARTUP_BUFFER_SECONDS=8
```

机器人需要先被邀请进 KOOK 服务器，并拥有查看、加入目标语音频道的权限。服务器和语音频道会自动出现在网页选择器中，不需要把 ID 写进源码。

## 本地开发

```bash
python3 -m venv venv
./venv/bin/python -m pip install -r requirements.txt
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

设置后台支持网易云扫码自动获取 Cookie、手动替换 Cookie，以及 QQ/微信扫码登录。
修改凭证的接口受 `MUSIC_SETTINGS_TOKEN` 保护，管理密钥只保存在浏览器当前会话。

网易云 Cookie 默认写入 `MusicBot/Cookie/`；QQ 音乐扫码凭证默认写入
`MusicBot/data/qqmusic/credential.json`，相关文件权限为 `0600`，
设备信息写入同目录。部署容器时应将该目录挂载到持久卷；也可以使用
`NETEASE_COOKIE` / `QQ_MUSIC_CREDENTIAL_JSON` 环境变量注入已有登录信息。

## 生产启动

在仓库根目录启动。`./serve.sh` 默认拉起 main 和 music（8004，Nginx 反代 `https://trashbox.tech/Music/`）：

```bash
./serve.sh
./serve.sh status
./serve.sh restart
```
