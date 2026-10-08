# 本地机器人凭据

实际密钥只放在下表中的本地文件，不提交 Git。示例文件只包含占位符。

| 服务 | 本地文件 | 字段 | 模板 |
| --- | --- | --- | --- |
| 点歌机 | `MusicBot/.env` | `MUSIC_BOT_TOKEN` | `MusicBot/.env.example` |
| 数据榜单与 GSI | `.env` 优先，兼容 `CS/config.ini` | `DATA_BOT_TOKEN` / `[Kook] Token` | `.env.example` / `CS/config.ini.example` |
| 主机器人常规功能 | `.env` 优先，兼容 `config/config.json` | `MAIN_BOT_TOKEN` / `token` | `.env.example` / `config/config.json.example` |
| Broadcast | `broadcast/config.ini` | `[kook] Token` | `broadcast/config.ini.example` |
| orderBot 测试机器人 | `orderBot/config.ini` | `[kook] Token` | `orderBot/config.ini.example` |

MusicBot 的正常入口 `run.py` 从本目录加载 `.env`；launcher 显式传入的监听地址和统一登录设置优先。音乐身份只读取 `MUSIC_BOT_TOKEN`，不会回退到主机器人 Token。
主机器人与数据机器人分别使用根目录 `.env` 的 `MAIN_BOT_TOKEN` 和 `DATA_BOT_TOKEN`。GitBot 读取自己 `.env` 的 `MAIN_BOT_TOKEN`，共用主机器人身份。KOOK OAuth Client ID/Secret 只由 TrashBox Backend 管理。
CS 和 Broadcast 不再从源码的硬编码值读取。不要把新密钥写回脚本、模板、日志或说明文档。
orderBot 的测试机器人身份保持不变；其使用主机器人身份的 HTTP 请求也优先读取 `MAIN_BOT_TOKEN`，避免轮换后继续使用旧 JSON Token。

## 本地与服务器启动职责

Mac 的 TrashBox 根启动器管理网站、中央认证和 Music Web/音乐进程：

```sh
cd /Users/lucas/Develop/project/TrashBox
./serve.sh start all
# 只启动音乐：
./serve.sh start music
```

该 `all` 不启动 KBot 主机器人和数据机器人。KBot 常规功能与 CS 榜单播报在独立 KBot 仓库中管理。
Mac 调试这两个核心进程时，在 KBot 根目录用两个终端分别前台启动（依赖已安装时）：

```sh
./.venv/bin/python -u KBot.py
# 另一个终端：
./.venv/bin/python -u CS/Scheduled_tasks.py
```

Ubuntu 上海服务器的 KBot 启动器使用 Linux `setsid`，`main` 组包含主机器人和 CS 数据榜单进程：

```sh
cd /home/ubuntu/KBot
./serve.sh start main
./serve.sh start music
./serve.sh status
```

Music 的统一会话接口由 TrashBox Backend 提供；根网站的启动器 `start all` 已负责中央认证、API 与 Music。
以上命令是操作说明，不代表本轮已经启动或重启。将新凭据写入本地 `.env` 不会更新既有进程的环境；旧进程继续使用启动时读到的 Token，授权重启后才会加载新值。

## 更新服务器前

这次移除了 Git 对三个实际配置文件的跟踪，但保留了本机文件。
**服务器首次拉取此变更前，必须把原配置备份到仓库外的私有目录；Git 拉取删除记录可能删除服务器上的旧文件。**
拉取后恢复配置并填写轮换后的密钥；`orderBot/config.ini` 是新增本地文件，启用该服务前也需准备。
本地忽略的配置不会通过 `git push/pull` 自动同步，需通过 SSH/SFTP 等安全通道单独更新。
不要覆盖 CS 的数据库、Steam 配置，或 MusicBot 的其他已配置项。

配置就绪后，根据正在使用的服务重启：

```sh
./serve.sh restart main
./serve.sh restart music
./serve.sh restart broadcast
# 仅在实际使用时重启：
./serve.sh restart gsi
./serve.sh restart order
```

## 提交前检查

```sh
python3 scripts/check_kook_secrets.py
# git add 完成后检查即将提交的内容：
python3 scripts/check_kook_secrets.py --staged
```

检查只打印文件名和行号，不打印密钥。脚本检查当前版本/提交索引，不检查 Git 全部历史，
也不能保证检测所有其他类型的秘密或所有编码形式。请同时使用 GitHub Secret Scanning / Push Protection。
本地文件权限建议为 `600`。`.gitignore` 防止普通误提交，但无法阻止 `git add -f`。

## 已泄露的旧密钥

必须在 KOOK 平台撤销旧密钥；删除当前文件或添加 `.gitignore` 不会删除 Git 历史、fork、克隆或缓存中的副本。
历史改写需要单独安排并协调强制推送，本次没有改写历史或自动推送。
orderBot 另有此前硬编码的测试凭据，本次只迁移保存位置，没有取得其新凭据，应单独轮换。
