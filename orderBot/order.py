from khl import *
from khl.card import Card, CardMessage, Module, Types, Element, Struct
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, date
import traceback
import aiohttp
from urllib.parse import quote
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot_credentials import load_ini_token

# 用 json 读取 config.json，装载到 config 里
with (Path(__file__).resolve().parents[1] / 'config' / 'config.json').open('r', encoding='utf-8') as f:
    config = json.load(f)

# init Bot
KOOKtoken=config['token']
bot = Bot(load_ini_token(Path(__file__).with_name('config.ini'))) #测试机

year, week, _ = datetime.now().isocalendar()

# 预定义的Emoji列表（只需要emoji_id部分）
REACTION_EMOJIS = [
    "8883870155357548/MFAiBgjoHI074074",  # 三角洲
    "8883870155357548/JdBWKq8SYl074074",   # 炉石传说
    "8883870155357548/0AK6HDj08o01c01c",   # OW2
    "8883870155357548/tIVDHmGdHB0d60d6",   # CS2
    "8883870155357548/VHJDgZ6HUi00w00w",   # 三国杀
    "8883870155357548/9nYdOzYm9Y00w00w",   # Apex
    "8883870155357548/gwvrxwA1Tn00w00w",   # 永劫无间
    "8883870155357548/5hLMc51RXx00w00w"    # COD
]


async def add_reactions(msg_id: str):
    """为指定消息添加多个表情回应"""
    headers = {
        'Authorization': f'Bot {KOOKtoken}',
        'Content-Type': 'application/json'
    }
    async with aiohttp.ClientSession() as session:
        for emoji_id in REACTION_EMOJIS:
            try:
                payload = {
                    "msg_id": msg_id,
                    "emoji": emoji_id
                }
                async with session.post(
                    "https://www.kookapp.cn/api/v3/message/add-reaction",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status != 200:
                        resp = await response.text()
                        print(f"添加表情失败: {resp}")
            except Exception as e:
                print(f"请求异常: {str(e)}")

async def get_kook_data():
    url = "https://kookapp.cn/api/guilds/8883870155357548/widget.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            return data

async def get_reaction():
    list_url = "https://kookapp.cn/api/v3/message/reaction-list"
    async with aiohttp.ClientSession() as session:
        async with session.get(list_url) as response:
            data = await response.json()
            return data



async def OrderCard():
    today = date.today()
    month = today.month
    day = today.day
    data = await get_kook_data()
    online_count = data['online_count']
    card = Card(
        Module.Header(Element.Text(f"{month}.{day} 玩什么？                                 当前在线：{online_count} 人", type=Types.Text.PLAIN))
    )
    # card.append(
    #     Module.ActionGroup(
    #         Element.Button("➕️",value='+',click=Types.Click.RETURN_VAL,theme=Types.Theme.INFO),
    #     )
    # )
    return card

@bot.command(name='order')
async def order_cmd():
    ch = await bot.client.fetch_public_channel("6711328063322818")
    try:
        card = await OrderCard()
        order_msg = await ch.send(CardMessage(card))
        # 添加表情回应
        await add_reactions(order_msg['msg_id'])
    except:
        print(traceback.format_exc())










# 存储用户反应的全局字典
# 结构：{ (msg_id, emoji): [user_data1, user_data2] }
reaction_users = {}

async def fetch_reaction_users(msg_id: str, emoji: str):
    """获取指定消息的表情点击用户列表"""
    headers = {'Authorization': f'Bot {KOOKtoken}'}
    encoded_emoji = quote(emoji, safe='')  # 严格编码
    
    async with aiohttp.ClientSession() as session:
        try:
            url = f"https://www.kookapp.cn/api/v3/message/reaction-list?msg_id={msg_id}&emoji={encoded_emoji}"
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data['code'] == 0:
                        return data.get('data', [])
                    else:
                        print(f"API返回错误：{data['message']}")
                else:
                    print(f"请求失败，状态码：{resp.status}")
        except Exception as e:
            print(f"获取用户列表异常：{str(e)}")
        return []

def update_reaction_data(msg_id: str, emoji: str, user_data: dict):
    """更新用户反应数据"""
    key = (msg_id, emoji)
    # 去重处理
    existing = [u for u in reaction_users.get(key, []) if u['id'] != user_data['id']]
    existing.append(user_data)
    reaction_users[key] = existing

@bot.on_event(EventTypes.ADDED_REACTION)
async def on_reaction_add(b: Bot, event: Event):
    """监听表情添加事件"""
    # 提取事件数据
    msg_id = event.body['msg_id']
    emoji_id = event.body['emoji']['id']
    user_id = event.body['user_id']
    
    # 获取完整用户列表
    users = await fetch_reaction_users(msg_id, emoji_id)
    
    # 找到当前触发事件的用户
    current_user = next((u for u in users if u['id'] == user_id), None)
    
    if current_user:
        # 更新存储
        update_reaction_data(msg_id, emoji_id, current_user)
        print(f"记录用户反应：{current_user['username']} 点击了 {emoji_id}")
    else:
        print("未找到相应用户数据")

# 查询示例（可通过命令触发）
@bot.command(name='check-reactions')
async def check_reactions():
    print(users = reaction_users.get((msg_id, emoji), []))
    # """查询指定消息的表情点击情况"""
    # users = reaction_users.get((msg_id, emoji), [])
    # if users:
    #     response = "\n".join([f"{u['nickname']} ({u['username']}#{u['identify_num']})" for u in users])
    #     await ctx.reply(f"已记录的用户：\n{response}")
    # else:
    #     await ctx.reply("暂无记录数据")


if __name__ == "__main__":
    # scheduler = AsyncIOScheduler()
    # scheduler.add_job(order_cmd, 'cron', hour=14, minute=32,misfire_grace_time=60)
    bot.run()
