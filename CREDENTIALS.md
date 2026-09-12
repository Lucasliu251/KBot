# 本地机器人凭据

实际密钥只放在下表中的本地文件，不提交 Git。示例文件只包含占位符。

| 服务 | 本地文件 | 字段 | 模板 |
| --- | --- | --- | --- |
| 点歌机 | `MusicBot/.env` | `MUSIC_BOT_TOKEN` | `MusicBot/.env.example` |
| CS 小助手与 GSI | `CS/config.ini` | `[Kook] Token` | `CS/config.ini.example` |
| 微信监控 | `config/config.json` | `token` | `config/config.json.example` |
| Broadcast | `broadcast/config.ini` | `[kook] Token` | `broadcast/config.ini.example` |
| orderBot 测试机器人 | `orderBot/config.ini` | `[kook] Token` | `orderBot/config.ini.example` |

MusicBot 的正常入口 `run.py` 明确从本目录加载 `.env`，覆盖同名的父进程环境变量。
CS 和 Broadcast 不再从源码的硬编码值读取。不要把新密钥写回脚本、模板、日志或说明文档。
orderBot 的测试机器人身份保持不变；它原本使用微信监控凭据发送部分 HTTP 请求的行为也未更改。

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
