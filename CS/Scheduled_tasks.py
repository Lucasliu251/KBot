import os
import logging
from khl import Bot, Event, EventTypes
from khl.card import Card, CardMessage, Module, Types, Element, Struct
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
import pandas as pd
import json


# 设置日志记录
logging.basicConfig(level=logging.INFO)
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

    previous_file = os.path.join("CS/data/week", f"weekly_stats_{year}-{week-1}.csv")
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
    logging.info(f"{datetime.now()} 每日榜单定时任务开始")

    # 调用get_data.py获取最新数据
    print('收集中')
    os.system('python CS/get_data.py')
    
    # 读取最新的统计数据
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    file_path = os.path.join("CS/data", f"player_stats_{today}.txt")
    logging.info(f"读取 {file_path} 中")
    data = read_data_file(file_path)

    # 构建并发送Kook富文本消息
    if data:
        message = Daily_message_A(data)
        ch = await bot.client.fetch_public_channel("2506365885049703")
        print('发送中')
        await ch.send(CardMessage(message))
    else:
        print("无数据可发送")

# 定时任务：发送周报
async def send_weekly_stats():
    year, week, _ = datetime.now().isocalendar()
    logging.info(f"{datetime.now()} 周数据任务开始")
    os.system('python CS/get_weekly.py')
    file_path = os.path.join("CS/data/week", f"weekly_stats_{year}-{week}.csv")
    logging.info(f"读取 {file_path} 中")
    data = pd.read_csv(file_path)
    data = data.dropna(subset=['Score'])     #筛选出 'Score' 列中非 NaN 的行
    message = Weekly_message(data)
    ch = await bot.client.fetch_public_channel("2506365885049703")
    await ch.send(CardMessage(message))

# 设置定时任务，每天23:00执行
scheduler = AsyncIOScheduler()
scheduler.add_job(send_daily_stats, 'cron', hour=23, minute=30,misfire_grace_time=60)
scheduler.add_job(send_weekly_stats,'cron', day_of_week='sat',hour=20,minute=00, misfire_grace_time=60)
scheduler.start()

# 运行Kook机器人
bot.run()
print('初号机上线')
