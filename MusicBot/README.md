# KBot Music Console

Vue 3 + TypeScript + Vite 控制台，Python/Flask 提供 KOOK 服务；项目内置并
由 `run.py` 管理本机 `api-enhanced`，不依赖任何公共网易云 API 实例。

搜索菜单支持“网易云｜Bilibili｜QQ音乐”三音源，默认仍为网易云。QQ音乐通过内置的
[L-1124/QQMusicApi](https://github.com/L-1124/QQMusicApi) 0.7.2 适配，第一次
使用时在 Banner 右侧齿轮“音乐服务后台”中使用 QQ 或微信扫码登录会员账号。

点击 Banner 齿轮即可直接查看网易云引擎是否为“本项目本地解析引擎”、版本和
监听地址，无需服务器命令。歌词右上角“译”按钮会在当前歌曲存在逐句翻译时启用，
开启后按“上方原文、下方译文”随时间轴滚动；网易云和 QQ 音乐均支持。

Bilibili 通过项目内嵌的 `yt-dlp` 与 B站 Web API 提供关键词、BV/AV、短链、
完整链接和多P解析；只提取临时音频地址，不下载或持久化视频文件。单个视频或
分P硬限制为 1 小时，直播暂不支持。B站不执行任何歌词搜索，统一显示无歌词提示。

搜索抽屉默认显示“大家推荐”，服务器成员可用 KOOK 身份一键推荐或撤回任意
音源的歌曲；同一用户对同一首歌只计一票。推荐卡按“最新”或推荐人数“人气”
透明排序，原网易云 / QQ 音乐平台榜单保留在相邻页签。推荐记录保存在本机
`data/recommendations.sqlite3`，不保存 KOOK OAuth AccessToken。

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
NETEASE_API_HOST=127.0.0.1
NETEASE_API_PORT=8005
MUSIC_API_BASE=http://127.0.0.1:8005
MUSIC_PRELOAD_SECONDS=600
MUSIC_STREAM_BUFFER_SECONDS=45
MUSIC_STARTUP_BUFFER_SECONDS=8
TRASHBOX_AUTH_SESSION_URL=http://127.0.0.1:2026/api/v1/auth/session
TRASHBOX_LOGIN_URL=/login
TRASHBOX_AUTH_FRONTEND_ORIGIN=
MUSIC_SESSION_COOKIE_SECURE=True
```

机器人需要先被邀请进 KOOK 服务器，并拥有查看、加入目标语音频道的权限。服务器和语音频道会自动出现在网页选择器中，不需要把 ID 写进源码。

“大家推荐”要求主站账号关联 KOOK，Music 会用音乐机器人检查服务器成员身份。主机器人 OAuth 的 Client ID、Client Secret 与回调只配置在 TrashBox Backend；Music 不再单独交换授权码。
生产环境必须使用 HTTPS、随机的 `SECRET_KEY`，并设置
`MUSIC_SESSION_COOKIE_SECURE=True`。

网易云组件使用锁定版本的
[`@neteasecloudmusicapienhanced/api`](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced)。
它只监听 `127.0.0.1:8005`，不应开放防火墙端口或配置 Nginx 反代。历史
腾讯云/第三方公共地址会被配置层自动迁移到本地地址。

## 本地开发

```bash
python3 -m venv venv
./venv/bin/python -m pip install -r requirements.txt
npm install
npm run dev
```

需要 Node.js 22.12 或更高版本。`npm run dev` 会由 Flask 进程自动管理本地
网易云 API（8005），同时启动 Flask API（8004）与 Vite（5173）。只想查看界面预览时可运行：

```bash
npm run dev:web
```

## 频道地址

- `/Music`：打开频道选择器。
- `/Music/<频道ID>`：直接打开指定语音频道的控制台。

Flask 会从 `static/music-console` 加载生产构建产物。仓库根目录的 `serve.sh`
会在每次启动或重启 music 时，按依赖声明变化自动同步 Node/Python 依赖，并始终执行
`npm run build`，因此部署更新可直接运行：

```bash
./serve.sh restart music
```

也可以在 `MusicBot` 目录手动执行 `npm run build` 做独立构建检查。

设置后台支持网易云扫码自动获取 Cookie、手动替换 Cookie，以及 QQ/微信扫码登录。
修改凭证的接口受 `MUSIC_SETTINGS_TOKEN` 保护，管理密钥只保存在浏览器当前会话。

网易云 Cookie 默认写入 `MusicBot/Cookie/`，只发送给同机 8005 后再访问网易云；QQ 音乐扫码凭证默认写入
`MusicBot/data/qqmusic/credential.json`，相关文件权限为 `0600`，
设备信息写入同目录。部署容器时应将该目录挂载到持久卷；也可以使用
`NETEASE_COOKIE` / `QQ_MUSIC_CREDENTIAL_JSON` 环境变量注入已有登录信息。

## 生产启动

齿轮设置页解锁后可设置“歌曲渐入渐出”，默认开启、4秒，范围1–12秒。
当前曲尾渐弱、下一首曲头渐强；手动上一首/下一首也会渐出，重复点击切歌可立即跳过过渡。
本版是顺序淡出/淡入，不混合两首音轨，也不做节拍匹配。暂停和清空保持即时响应。
设置按播放器统一保存到 `data/playback-settings.json`，从下一首生效，服务重启后保留。
容器部署需持久化此文件。Apple新版AutoMix时长动态；这里参考固定Crossfade的4秒初始值。

在仓库根目录启动。`./serve.sh` 默认拉起 main 和 music（8004，Nginx 反代 `https://trashbox.tech/Music/`）：

```bash
./serve.sh
./serve.sh status
./serve.sh restart
```
# 语音频道自动管理与播放卡片

音乐机器人启动后，独立后台线程会每 15 秒查询当前语音频道的成员。
仅剩机器人时，5 秒后再次确认；仍无人则清空当前歌曲、队列及所属预加载缓存，停止推流并退出。
暂停、等待点歌时同样生效；成员请求失败或格式异常时保持连接，不把网络故障当作无人。

播放时向当前语音频道的文字区域发送一张卡片，此次连接期间始终编辑同一条消息，
每 10 秒更新歌曲、封面、专辑、艺术家、实际进度与音量。暂停时进度冻结，退出后标注已结束。
右上角按钮打开该频道的点歌网页，不另占按钮行。封面和曲目信息居中，底部小字显示音源、模式、音量和进度；没有底排控制按钮。进度为状态展示，不支持直接拖动。
机器人需要查看频道成员、在该频道发送消息的权限；失败会写入后台日志，不影响音频推流。

在 `MusicBot/.env` 中可设置卡片按钮的公开网址（无需末尾频道 ID）：

```dotenv
MUSIC_PUBLIC_URL=https://trashbox.tech/Music
```

未设置时使用上述地址。修改后重启音乐服务生效。此功能不需要新增端口或 OAuth 权限。

## 交叉切歌

设置页的一行滑条控制渐入/渐出时长（1–12 秒，默认 4 秒），旁边的“交叉切歌”开关默认开启，修改自动保存，从下一首生效。
开启时，当前曲淡出到一半后开始混入已预加载的下一首；例如设置 4 秒，最后 2 秒为双曲重叠段。
交接后继续消费下一首剩余的采样，不重播开头，也不重新预热。两首共用音量平滑和 RTP 编码器。
关闭时恢复顺次淡出、淡入。没有下一首或队首缓存尚不足时自动退回普通过渡，不阻塞音频发送等待下载。
交叉交接期间不强制 GC，旧解码器异步回收；维护会留到没有交叉接棒的切换阶段。


## TrashBox 统一登录

所有控制台页面、Music API 和 SocketIO 使用主站 `trashbox_session`，每次读取验证均不延长会话。
`TRASHBOX_AUTH_SESSION_URL` 默认为本机 2026 端口的 `/api/v1/auth/session`；未登录返回主站 `/login?return_to=/Music/...`。
写操作必须提供中央 `X-CSRF-Token`。只有用户实际在前台导航或交互时，页面才调用中央 activity 更新闲置时间。
本机统一 launcher 设置 `TRASHBOX_AUTH_FRONTEND_ORIGIN=http://127.0.0.1:5175`，Music 代理同源的登录/账号/认证资源及 `/api/v1/web-auth/challenges*` 小程序二维码接口；生产由 Nginx 提供这些路径。
推荐继续要求关联 KOOK 并通过音乐机器人的 `guild/user-list?filter_user_id=...` 验证服务器成员身份。
历史推荐仅按中央服务验证过的 KOOK subject 和合并账号 alias_ids 关联；原 SQLite 行均保留，重复推荐按中央账号计数，归属冲突返回错误。
`GET /healthz` 为不含账号或运行数据的本机启动探活接口。


## 本机认证 QA 模式

上海服务器音乐机器人仍运行时，本机可只验证统一登录、页面、API 和 SocketIO：

```sh
cd /Users/lucas/Develop/project/TrashBox
MUSIC_HTTP_ONLY=1 ./serve.sh start all
```

开关由 launcher 继承，`run.py` 不覆盖它；缺省 False 保持正常音乐行为。
该模式跳过 KOOK Gateway 线程和频道伴随服务，并让音频播放控制 API 返回明确的 QA 提示，避免测试点击启动新的语音连接。
`/healthz` 的 `music_http_only` 字段用于确认测试模式；服务器正常运行时保持 False。
