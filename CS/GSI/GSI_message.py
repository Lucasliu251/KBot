import time
import requests
from khl import Bot, Event, EventTypes
from khl.card import Card, CardMessage, Module, Types, Element, Struct
import aiohttp
import json




# API地址
API_URL = "http://47.115.75.168:3000/gsi"
botoken = '1/MzA5MDc=/lOziyhZw7gRaEn02qJfdeg=='

# 启动KOOK机器人并发送消息
bot = Bot(token=botoken)  # 替换为你的KOOK机器人token

def fetch_game_data():
    response = requests.get(API_URL)
    if response.status_code == 200:
        return response.json()
    else:
        print("获取失败:", response.status_code)
        return None



def build_kook_message(game_data):
    cm = CardMessage()

    match_info = game_data["比赛信息"]
    teams_info = game_data["队伍信息"]

    # 比赛信息部分
    c = Card(
        Module.Header(f'{time.strftime("%Y.%m.%d")}_{match_info["比赛地图"]}_比赛中'),
        Module.Divider()
    )
    c.append(
        Module.Section(
            Struct.Paragraph(
                3,
                Element.Text(f"**比分**\n{match_info['总比分']}", type=Types.Text.KMD),
                Element.Text(f"**时间**\n{time.strftime('%H:%M')}", type=Types.Text.KMD),
                Element.Text(f"**模式**\n{match_info['比赛模式']}", type=Types.Text.KMD),
            )
        )
    )
    c.append(
        Module.Section(
            Struct.Paragraph(
                3,
                Element.Text(f"**当前阶段**\n{match_info['当前回合阶段']}", type=Types.Text.KMD),
                Element.Text(f"**回合倒计时**\n1:55", type=Types.Text.KMD),  # 假设固定的倒计时
                Element.Text(f"**炸弹状态**\n{match_info['炸弹状态']}", type=Types.Text.KMD),
            )
        )
    )
    c.append(Module.Divider())
    c.append(Module.Header("我方队伍"))

    # 队伍信息部分
    for player_id, player_data in teams_info.items():
        stats = player_data['玩家比赛统计']
        c.append(
            Module.Section(
                Struct.Paragraph(
                    3,
                    Element.Text(f"**昵称**\n{player_id}", type=Types.Text.KMD),
                    Element.Text(f"**K-D**\n{stats['击杀数']}-{stats['死亡数']}", type=Types.Text.KMD),
                    Element.Text(f"**MVP**\n{stats['MVP次数']}", type=Types.Text.KMD),
                )
            )
        )

    # MVP 部分
    mvp_player = max(
        teams_info.items(),
        key=lambda x: int(x[1]['玩家比赛统计'].get('MVP次数', 0))
    )[0]
    c.append(Module.Context(f"本场MVP是："))
    c.append(Module.Context(f"**{mvp_player}**"))

    return c

async def update_msg(m_id,cont):
    url = "https://www.kookapp.cn/api/v3/message/update"
    headers={f'Authorization': f"Bot {botoken}",'Content-Type': 'application/json'}
    data = {
        'msg_id': m_id,
        'content': cont
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            if response.status == 200:
                    result = await response.json()
                    if result['code'] == 0:
                        print('更新成功')
                        return 'message'
                    else:
                        print(f"退出失败: {result['message']} (错误码: {result['code']})")
                        return None
            else:
                print(f"请求失败: {response.status}")
                return None


message_id = None

@bot.task.add_interval(seconds=5)
async def send_game_update():
    global message_id
    game_data = fetch_game_data()
    if game_data:
        card_msg = build_kook_message(game_data)
        ch = await bot.client.fetch_public_channel("2506365885049703")
        if message_id is None:
            #首次发送卡片
            sent_msg = await ch.send(CardMessage(card_msg))
            # 保存 message_id
            message_id = sent_msg['msg_id']
        else:
            # 编辑已发送的卡片消息
            await update_msg(str(message_id), json.dumps(CardMessage(card_msg)))

        

bot.run()
