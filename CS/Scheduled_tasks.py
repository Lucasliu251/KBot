import asyncio
import os
import logging
from khl import Bot, Event, EventTypes
from khl.card import Card, CardMessage, Module, Types, Element, Struct
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
import json


# 设置日志记录
logging.basicConfig(level=logging.INFO)

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
        'KD': []
    }
    for line in lines:
        parts = line.split()
        if len(parts) >= 3:
            KD = float(parts[6])
            if KD != 0:  # 过滤KD为0的数据
                data['rank'].append(parts[0])
                data['nickname'].append(parts[1])
                data['kills'].append(parts[4])
                data['KD'].append(str(KD))
    return data

# 构建Kook富文本消息
def build_kook_message(data):

    rank_nickname = ["{} {}".format(rank, nickname) for rank, nickname in zip(data['rank'], data['nickname'])]
   # 构建卡片消息的 JSON 对象
    card = Card(
        Module.Header(Element.Text("「互联网垃圾桶」每日榜单", type=Types.Text.PLAIN))
    )
    card.append(
        Module.Section(
            Struct.Paragraph(
                3,
                Element.Text(("**Rank**\n" + "\n".join(rank_nickname)),type=Types.Text.KMD),
                Element.Text(("**★StarTrack™️**\n" + "\n".join(data['kills'])),type=Types.Text.KMD),
                Element.Text(("**K/D 比**\n" + "\n".join(data['KD'])),type=Types.Text.KMD)
            )
        )
    )
    card.append(Module.Divider()) # 分隔符
    card.append(
        Module.Countdown(
        datetime.now() + timedelta(seconds=86400), mode=Types.CountdownMode.DAY
    )
    )
    return card



# 定时任务：发送每日统计
async def send_daily_stats():
    logging.info(f"{datetime.now()} 定时任务开始")

    # 调用get_data.py获取最新数据
    print('收集中')
    os.system('python CS/get_data.py')
    
    # 读取最新的统计数据
    today = datetime.now().strftime('%Y-%m-%d')
    file_path = os.path.join("CS/data", f"player_stats_{today}.txt")
    logging.info(f"读取 {file_path} 中")
    data = read_data_file(file_path)

    # 构建并发送Kook富文本消息
    if data:
        message = build_kook_message(data)
        ch = await bot.client.fetch_public_channel("2506365885049703")
        print('发送中')
        await ch.send(CardMessage(message))
    else:
        print("无数据可发送")

# 设置定时任务，每天23:00执行
scheduler = AsyncIOScheduler()
scheduler.add_job(send_daily_stats, 'cron', hour=23, minute=30,misfire_grace_time=60)
scheduler.start()

# 运行Kook机器人
bot.run()
print('初号机上线')
