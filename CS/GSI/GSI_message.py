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
bot = Bot(token=botoken)  

whitelist = {
    "76561199047005402": "Lucas",
    "76561199379568178": "这很机车",
    "76561198812098457": "lilt",
    "76561198819631157": "Ari",
    "76561199501933725": "和明天相逢",
    "76561199748267569": "yuyu"
}

def fetch_game_data():
    response = requests.get(API_URL)
    if response.status_code == 200:
        return response.json()
        # # 检查数据中是否有比赛，并选择第一个比赛
        # if len(game_data_list) > 0:
        #     first_game_data = game_data_list[0]  # 读取第一场比赛的数据
        #     return first_game_data
        # else:
        #     print("没有可用的比赛数据")
        #     return None
    else:
        print("获取失败:", response.status_code)
        return None


def build_kook_message(game_data,timer):
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
                    Element.Text(f"**回合倒计时**\n{timer // 60}:{timer % 60:02d}", type=Types.Text.KMD),  # 动态刷新的倒计时
                    Element.Text(f"**炸弹状态**\n{match_info['炸弹状态']}", type=Types.Text.KMD),
                )
            )
        )
        c.append(Module.Divider())
        c.append(Module.Header("我方队伍"))

        # 队伍信息部分
        c.append(
            Module.Section(Struct.Paragraph(3,Element.Text("**昵称**"),Element.Text("**K-D-A**"),Element.Text("**MVP**")))
        )
        for player_id, player_data in teams_info.items():

            nickname = whitelist.get(player_id, player_id)  # 如果字典中没有该ID，使用原ID
            stats = player_data['玩家比赛统计']
            if player_data['玩家状态']['生命值'] == 0:
                # 给死亡玩家加删除线
                c.append(
                    Module.Section(
                        Struct.Paragraph(
                            3,
                            Element.Text(f"*~~{nickname}~~*", type=Types.Text.KMD),
                            Element.Text(f"{stats['击杀数']}-{stats['死亡数']}-{stats['助攻数']}", type=Types.Text.KMD),
                            Element.Text(f"{stats['MVP次数']}", type=Types.Text.KMD),
                        )
                    )
                )
            else:
                c.append(
                    Module.Section(
                        Struct.Paragraph(
                            3,
                            Element.Text(f"{nickname}", type=Types.Text.KMD),
                            Element.Text(f"{stats['击杀数']}-{stats['死亡数']}", type=Types.Text.KMD),
                            Element.Text(f"{stats['MVP次数']}", type=Types.Text.KMD),
                        )
                    )
                )

        

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
            
async def delete_msg(m_id):
    url = "https://www.kookapp.cn/api/v3/message/delete"
    headers={f'Authorization': f"Bot {botoken}",'Content-Type': 'application/json'}
    data = {
        'msg_id': m_id
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            if response.status == 200:
                    result = await response.json()
                    if result['code'] == 0:
                        print('删除成功')
                        return 'message'
                    else:
                        print(f"退出失败: {result['message']} (错误码: {result['code']})")
                        return None
            else:
                print(f"请求失败: {response.status}")
                return None


message_id = None



        































is_gameover = False  # 比赛是否结束

class Game:
    def __init__(self, bot):
        self.bot = bot
        self.message_id = message_id  # 用于记录之前发送的卡片消息ID
        self.game_state = 'not_started'  # 比赛状态
        self.round_phase = 'freezetime'  # 当前回合阶段
        self.timer = 0  # 回合倒计时
        
        self.player_status = {}  # 玩家状态，记录每个玩家的生命值
        
        

    #主函数
    async def update_game_status(self, game_data):
        """
        监听比赛状态、回合阶段、倒计时和玩家信息
        """
        # 获取比赛状态
        game_state = game_data["比赛信息"]["比赛状态"]
        self.round_phase = game_data["比赛信息"]["当前回合阶段"]
        print(game_state,self.round_phase)
        
        if game_state == "gameover":
            global message_id,is_gameover
            print(is_gameover)
            if not is_gameover:
                await self.handle_gameover(game_data)
                is_gameover = True
            message_id = None
            return
        
        if game_state == "live":
            is_gameover = False
            # 更新回合倒计时
            self.update_round_timer(game_data)
            countdown = self.timer

            # 更新卡片内容
            await self.send_game_update(game_data)







    async def send_game_update(self, game_data):
        global message_id
        
        if game_data:
            card_msg = build_kook_message(game_data, self.timer)
            ch = await bot.client.fetch_public_channel("2506365885049703")
            if message_id is None:
                #首次发送卡片
                sent_msg = await ch.send(CardMessage(card_msg))
                # 保存 message_id
                message_id = sent_msg['msg_id']
            else:
                # 编辑已发送的卡片消息
                await update_msg(str(message_id), json.dumps(CardMessage(card_msg)))
    
    def update_round_timer(self, game_data):
        """
        更新回合倒计时
        """
        if self.round_phase == "freezetime":
            self.timer = 12  # freezetime 阶段默认 10 秒
        elif self.round_phase == "live":
            self.timer = 1 * 60 + 55  # live 阶段默认 1:55
            if game_data["比赛信息"].get("炸弹安放"):
                self.timer = 40  # 如果炸弹安放，设置为 40 秒
        elif self.round_phase == "over":
            self.timer = 0  # 回合结束，时间冻结

        

    async def handle_gameover(self, game_data):
        """
        处理比赛结束时的逻辑
        """
        # 删除之前的卡片消息
        await delete_msg(message_id)

        # 计算所属阵营的胜负情况
        # my_team = game_data["队伍信息"]["76561199047005402"]["阵营"]
        # score_ct = game_data["比赛信息"]["总比分"]["CT"]
        # score_t = game_data["比赛信息"]["总比分"]["T"]
        # if (my_team == "CT" and score_ct > score_t) or (my_team == "T" and score_t > score_ct):
        #     result = "你所在的阵营获胜！"
        # else:
        #     result = "你所在的阵营失败！"

        # 发送比赛结束的卡片消息
        gameover_card = self.end_card(game_data)
        ch = await bot.client.fetch_public_channel("2506365885049703")
        await ch.send(CardMessage(gameover_card))

        

    
    def end_card(self, game_data):

        c = Card(
            Module.Header(f'{time.strftime("%Y.%m.%d")}_{game_data["比赛信息"]["比赛地图"]}_比赛回顾'),
            Module.Divider()
        )
        # 获取玩家所处阵营
        player_steam_id = None

        # 遍历白名单，找到能够获取到数据的steam_id
        for steam_id, nickname in whitelist.items():
            if steam_id in game_data["队伍信息"]:
                player_steam_id = steam_id
                break
        if player_steam_id is None:
            raise ValueError("在白名单中未找到有效的用户")
        
        player_team = game_data["队伍信息"][player_steam_id]["阵营"]

        if player_team == "T":
            opposing_team = "CT"
        else:
            opposing_team = "T"

        # emoji的映射
        emoji_mapping = {
            "t_win_bomb": "💥",
            "t_win_elimination": "💀",
            "ct_win_defuse": "🛠",
            "ct_win_time": "⏱",
            "ct_win_elimination": "☠"
        }

        # 构建emoji序列
        emojis = []
        round_results = game_data["比赛信息"]["回合结算"]
        for round_num, result in round_results.items():
            if int(round_num) <= 12:
                if opposing_team in result:
                    emojis.append(emoji_mapping.get(result, ""))
                else:
                    emojis.append(emoji_mapping.get(result, ""))
            else:
                if player_team in result:
                    emojis.append(emoji_mapping.get(result, ""))
                else:
                    emojis.append(emoji_mapping.get(result, ""))

        # 添加竖线分隔符
        if len(emojis) >= 13:
            emojis.insert(12, "🔄")

        # 判断比赛是否获胜，并在末尾添加🏆或🏳
        winning_side = game_data["比赛信息"]["当前回合胜利方"]
        if winning_side == player_team:
            emojis.append("🏆")
        else:
            emojis.append("🏳")

        # 拼接emoji序列
        emoji_str = "".join(emojis)

        # 将emoji添加到卡片消息中
        c.append(Module.Section(emoji_str))


        # MVP 部分
        mvp_player = max(
            game_data["队伍信息"].items(),
            key=lambda x: int(x[1]['玩家比赛统计'].get('MVP次数', 0))
        )[0]
        _mvp = whitelist.get(mvp_player, )
        c.append(Module.Context(f"本场MVP是："f"**{_mvp}**"))

        return c


    


@bot.task.add_interval(seconds=1)
async def GSItask():
    # 初始化Game类
    game = Game(bot)
    game_data = fetch_game_data()
    await game.update_game_status(game_data)

bot.run()



















