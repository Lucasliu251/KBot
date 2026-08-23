import os
import fcntl
import logging
from khl import Bot, Event, EventTypes
from khl.card import Card, CardMessage, Module, Types, Element, Struct
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
import pandas as pd
import json
import subprocess
import sys
from pathlib import Path

CS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = CS_DIR.parent
DATA_DIR = CS_DIR / 'data'
WEEK_DIR = DATA_DIR / 'week'
# 默认指向同级仓库 TrashBox-Server/Backend；可用环境变量覆盖
TRASHBOX_BACKEND_DIR = Path(os.getenv(
    'TRASHBOX_BACKEND_DIR',
    PROJECT_DIR.parent / 'TrashBox-Server' / 'Backend',
))


# 设置日志记录
logging.basicConfig(level=logging.INFO)
INSTANCE_LOCK_PATH = PROJECT_DIR / '.scheduled_tasks.lock'
_INSTANCE_LOCK_FD = None


def acquire_singleton_lock():
    """保证全机只有一份 Scheduled_tasks 在跑，避免重复发 KOOK 卡片。

    @returns: 持有锁的文件对象，进程退出前不可关闭
    @changelog
    - 2026-08-23: serve.sh PID 丢失会双开，加文件锁兜底 (Author: KBot)
    """
    global _INSTANCE_LOCK_FD
    lock_fd = open(INSTANCE_LOCK_PATH, 'w', encoding='utf-8')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logging.error('Scheduled_tasks 已在运行（%s），退出以免重复发卡片', INSTANCE_LOCK_PATH)
        sys.exit(0)
    lock_fd.write(str(os.getpid()))
    lock_fd.flush()
    _INSTANCE_LOCK_FD = lock_fd
    return lock_fd


acquire_singleton_lock()


def run_optional_script(script_path: Path, description: str) -> bool:
    """运行旁路脚本；文件不存在或失败时只记日志，不中断榜单发送。

    @param script_path: 脚本绝对路径
    @param description: 日志里的任务名
    @returns: 成功执行返回 True，跳过或失败返回 False

    @changelog
    - 2026-08-22: TrashBox Backend 未部署时不再让日报卡片发送失败 (Author: KBot)
    """
    if not script_path.is_file():
        logging.warning('跳过%s：找不到 %s', description, script_path)
        return False
    try:
        # cwd 必须是 Backend，否则 database/config 导入失败，.env 也读不到
        subprocess.run(
            [sys.executable, script_path],
            check=True,
            cwd=script_path.parent,
        )
        return True
    except subprocess.CalledProcessError:
        logging.exception('%s 执行失败，继续后续流程', description)
        return False
year, week, _ = datetime.now().isocalendar()
# 初始化Kook机器人
bot = Bot(token='1/MzA5MDc=/lOziyhZw7gRaEn02qJfdeg==')

# 读取和解析数据文件
def read_data_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()[1:]  # 跳过表头
    data = {
        'rank': [],
        'nickname': [],
        'kills': [],
        'KD': [],
        'HS': [],
        'DMG': [],
        'MVP': []
    }
    for line in lines:
        parts = line.split()
        if len(parts) >= 3:
            KD = float(parts[6])
            if KD != 0:  # 过滤KD为0的数据
                data['rank'].append(parts[0])
                data['nickname'].append(parts[1])
                data['kills'].append(parts[4])
                data['KD'].append(f"{KD:.2f}")
                data['HS'].append(parts[9])
                data['DMG'].append(parts[11])
                data['MVP'].append(parts[13])
    return data

# 构建Kook富文本消息
def Daily_message_A(data):

    rank_nickname = ["{} {}".format(rank, nickname) for rank, nickname in zip(data['rank'], data['nickname'])]
    kills_HS = ["{} ({})".format(kills, hs) for kills, hs in zip(data['kills'], data['HS'])]
    KD_MVP = ["{}  {}".format(KD, MVP) for KD, MVP in zip(data['KD'], data['MVP'])]
   # 构建卡片消息的 JSON 对象
    card = Card(
        Module.Header(Element.Text("「互联网垃圾桶」每日榜单", type=Types.Text.PLAIN))
    )
    card.append(
        Module.Section(
            Struct.Paragraph(
                3,
                Element.Text(("**Rank**\n" + "\n".join(rank_nickname)),type=Types.Text.KMD),
                Element.Text(("**★StarTrack™️**\n" + "\n".join(kills_HS)),type=Types.Text.KMD),
                Element.Text(("**K/D  MVP**\n" + "\n".join(KD_MVP)),type=Types.Text.KMD)
            )
        )
    )
    card.append(Module.Divider()) # 分隔符
    card.append(
        Module.Countdown(datetime.now() + timedelta(seconds=86400), mode=Types.CountdownMode.DAY)
    )
    return card

def Weekly_message(data):
    year, week, _ = datetime.now().isocalendar()
    Nickname = [name.ljust(20) for name in data['Nickname']]
    Activate = [str(activate).ljust(20) for activate in data['Activate']]
    Score = [str(score).ljust(20) for score in data['Score']]
    winner = data['Nickname'][0]
    activater = data.loc[data['Activate'].idxmax(), 'Nickname']

    previous_file = WEEK_DIR / f"weekly_stats_{year}-{week-1}.csv"
    previous_data = pd.read_csv(previous_file)
    defending_champion = previous_data['Nickname'][0]
    

    # 构建卡片消息的 JSON 对象
    card = Card(
        Module.Header(Element.Text(f"「互联网垃圾桶」{year}第{week}周积分榜", type=Types.Text.PLAIN))
    )
    card.append(
        Module.Section(f"> 本周MVP是：**(spl)(font){winner}(font)[warning](spl)**\n本周肝帝是：**(spl)(font){activater}(font)[warning](spl)**"),
    )
    if winner == defending_champion:
        card.append(
            Module.Context(f"{winner}又一次卫冕冠军！谁来给他打下来"),
        )
    else:
        card.append(
            Module.Context(f"{winner} 干掉了 {defending_champion} 登上了王座！"),
        )
    card.append(Module.Divider()) # 分隔符
    card.append(
        Module.Section(
            Struct.Paragraph(
                3,
                Element.Text(("**Nickname**\n" + "\n".join(Nickname)),type=Types.Text.KMD),
                Element.Text(("**Activate**\n" + "\n".join(Activate)),type=Types.Text.KMD),
                Element.Text(("**Score**\n" + "\n".join(Score)),type=Types.Text.KMD)
            )
        )
    )
    card.append(Module.Divider()) # 分隔符
    card.append(
        Module.Countdown(datetime.now() + timedelta(seconds=604800), mode=Types.CountdownMode.DAY)
    )
    return card



# 定时任务：发送每日统计
async def send_daily_stats():
    """收集当日数据并发送 KOOK 日报卡片。同一天只发送一次。

    @changelog
    - 2026-08-23: 日报改回 23:30；同日已发送则跳过，防止双实例连发 (Author: KBot)
    """
    logging.info(f"{datetime.now()} 每日榜单定时任务开始")
    today = datetime.now().strftime('%Y-%m-%d')
    sent_mark = DATA_DIR / f'.daily_card_sent_{today}'
    if sent_mark.exists():
        logging.warning('今日日报卡片已发送（%s），跳过', sent_mark)
        return

    # 调用get_data.py获取最新数据
    print('收集中')
    subprocess.run([sys.executable, CS_DIR / 'get_data_new.py'], check=True)
    # 风格标签脚本属于 TrashBox，本机未部署时跳过，避免打断 KOOK 卡片
    run_optional_script(TRASHBOX_BACKEND_DIR / 'calc_daily_styles.py', '风格标签计算')
    # 读取最新的统计数据
    file_path = DATA_DIR / f"player_stats_{today}.txt"
    logging.info(f"读取 {file_path} 中")
    data = read_data_file(file_path)

    # 构建并发送Kook富文本消息
    if data:
        message = Daily_message_A(data)
        ch = await bot.client.fetch_public_channel("2506365885049703")
        print('发送中')
        await ch.send(CardMessage(message))
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        sent_mark.write_text(datetime.now().isoformat(timespec='seconds'), encoding='utf-8')
    else:
        print("无数据可发送")

# 定时任务：发送周报
async def send_weekly_stats():
    year, week, _ = datetime.now().isocalendar()
    logging.info(f"{datetime.now()} 周数据任务开始")
    subprocess.run([sys.executable, CS_DIR / 'get_weekly.py'], check=True)
    file_path = WEEK_DIR / f"weekly_stats_{year}-{week}.csv"
    logging.info(f"读取 {file_path} 中")
    data = pd.read_csv(file_path)
    data = data.dropna(subset=['Score'])     #筛选出 'Score' 列中非 NaN 的行
    message = Weekly_message(data)
    ch = await bot.client.fetch_public_channel("2506365885049703")
    await ch.send(CardMessage(message))

async def wechat_notify():
    run_optional_script(TRASHBOX_BACKEND_DIR / 'send_report.py', '微信日报推送')

# APScheduler 3.11+ 的 AsyncIOScheduler.start() 必须在已有事件循环里调用，
# 因此放到 bot.on_startup，等 khl 起环后再启动。
# coalesce/max_instances：同一任务错过或重叠时只跑一份。
_job_opts = dict(misfire_grace_time=60, coalesce=True, max_instances=1, replace_existing=True)
scheduler = AsyncIOScheduler()
scheduler.add_job(send_daily_stats, 'cron', hour=23, minute=30, id='send_daily_stats', **_job_opts)
scheduler.add_job(send_weekly_stats, 'cron', day_of_week='sat', hour=20, minute=0, id='send_weekly_stats', **_job_opts)
scheduler.add_job(wechat_notify, 'cron', hour=23, minute=32, id='wechat_notify', **_job_opts)

@bot.on_startup
async def start_scheduler(_bot):
    """在 Kook 机器人事件循环就绪后启动定时任务。

    @param _bot: khl 传入的 Bot 实例，此处不使用
    @returns: None

    @changelog
    - 2026-08-22: APScheduler 3.11 要求 running loop，改为 on_startup 启动 (Author: KBot)
    - 2026-08-22: 旁路脚本目录改为 TrashBox-Server/Backend (Author: KBot)
    """
    if not scheduler.running:
        scheduler.start()
    logging.info('初号机调度器已启动')

# 运行Kook机器人
bot.run()
print('初号机上线')
