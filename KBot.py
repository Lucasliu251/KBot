import json
import traceback
from khl import *
import random
from random import randint
from spotipy import oauth2, Spotify
from spotipy.oauth2 import SpotifyOAuth,SpotifyOauthError
from flask import Flask, request, redirect,app,session,jsonify
import threading
import aiohttp
import asyncio
import logging
import time
import os
#import PyOfficeRobot




# 用 json 读取 config.json，装载到 config 里
with open(r'C:\Users\Administrator\Desktop\KooK_Bot\config\config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

# init Bot
KOOKtoken=config['token']
bot = Bot(KOOKtoken)

#投骰子模块
@bot.command(name='投骰子')
async def touzi(msg:Message):
    #reply
    random_number = randint(1,6)
    text = '投出一个'+str(random_number)
    await msg.reply(text)

    #send
    #await msg.ctx.channel.send('world only for you too',temp_target_id=msg.author.id)


#——————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
#获取歌词模块 
async def get_lyric(song):
    search_url = "http://music.163.com/api/search/pc"
    song_url_template = "http://music.163.com/api/song/media?id={}"
    
    payload = {"s": song, "offset": 0, "limit": 1, 'type': 1}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(search_url, data=payload) as response:
            search_response = await response.json()
            
            if 'result' not in search_response or 'songs' not in search_response['result'] or len(search_response['result']['songs']) == 0:
                return '未找到相关歌曲'
            
            song_data = search_response['result']['songs'][0]
            artists = song_data['artists']
            name = '/'.join(artist['name'] for artist in artists)
            song_id = song_data['id']
        
        lyric_url = song_url_template.format(song_id)
        async with session.get(lyric_url) as response:
            lyric_response = await response.json()
            
            try:
                if 'lyric' not in lyric_response or len(lyric_response['lyric']) <= 1:
                    return '暂无歌词'
                else:
                    return f'歌手: {name}\n{lyric_response["lyric"]}'
            except:
                return '纯音乐，无歌词'

@bot.command(name='lyric')
async def fetch_lyric(ctx, *, song_name: str):
    if not song_name:
        await ctx.reply('请提供歌曲名称')
        return
    lyric = await get_lyric(song_name)
    await ctx.reply(lyric)

#——————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
'''
#Spotify模块
# Spotify API认证
app = Flask(__name__)
sp_oauth = SpotifyOAuth(client_id=config['SPOTIPY_CLIENT_ID'],
                        client_secret=config['SPOTIPY_CLIENT_SECRET'],
                        redirect_uri=config['SPOTIPY_REDIRECT_URI'],
                        #scope="user-library-read")
                        scope='playlist-modify-private user-modify-playback-state')
token_info = sp_oauth.get_cached_token()
#Flask服务器
@app.route('/')
def index():
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/callback')
def callback():
    global token_info
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)
    return "授权成功！你现在可以关闭这个页面。"

def run_flask_app():
    app.run(port=8888)

# 在单独的线程中运行Flask服务器
threading.Thread(target=run_flask_app).start()

#获取访问令牌
def get_spotify_token():
    token_info = sp_oauth.get_cached_token()
    if not token_info:
        auth_url = sp_oauth.get_authorize_url()
        print(f"请打开以下链接并授权应用: {auth_url}")
        response = input("请输入重定向后的URL: ")
        code = sp_oauth.parse_response_code(response)
        token_info = sp_oauth.get_access_token(code)
        
    return token_info['access_token']

# 获取Spotify API客户端
token = get_spotify_token()
#sp = spotipy.Spotify(auth=token)
spotify = spotipy.Spotify(auth=token_info['access_token'])
#Spotofy机器人
#@bot.command(name='play')
#async def play_song(ctx: Message, *, song_name: str):
    #results = sp.search(q=song_name, type='track', limit=1)
    #if results['tracks']['items']:
        #track = results['tracks']['items'][0]
        #track_name = track['name']
        #track_artists = ', '.join(artist['name'] for artist in track['artists'])
        #track_url = track['external_urls']['spotify']
        #response = f"正在播放: {track_name} - {track_artists}\n{track_url}"
    #else:
        #response = "未找到相关歌曲"
    #await ctx.reply(response)



#添加播放队列
@bot.command(name='music')
async def music_cmd(msg: Message, *, song_name: str):
    results = spotify.search(q=song_name, limit=1, type='track')
    tracks = results['tracks']['items']
    
    if tracks:
        track_uri = tracks[0]['uri']
        spotify.add_to_queue(track_uri)
        await msg.reply(f'已将 {tracks[0]["name"]} 添加到播放队列。')
    else:
        await msg.reply('未找到相关歌曲。')
'''



# 设置日志记录
#logging.basicConfig(level=logging.DEBUG)

# Flask 服务器部分
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_COOKIE_NAME'] = 'spotify-login-session'

sp_oauth = oauth2.SpotifyOAuth(client_id=config['SPOTIPY_CLIENT_ID'],
                               client_secret=config['SPOTIPY_CLIENT_SECRET'],
                               redirect_uri=config['SPOTIPY_REDIRECT_URI'],
                               scope='user-read-private user-read-email playlist-modify-private user-modify-playback-state user-read-playback-state user-read-currently-playing')


global_token_info = None

def get_token():
    global global_token_info
    token_info = global_token_info
    if not token_info:
        return None
    now = int(time.time())
    is_expired = token_info['expires_at'] - now < 60
    if is_expired:
        token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
        global_token_info = token_info
    return token_info

@app.route('/')
def index():
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/callback')
def callback():
    global global_token_info
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)
    global_token_info = token_info
    return "授权成功，您可以关闭此窗口。"

@app.route('/get_token')
def get_token_endpoint():
    token_info = get_token()
    if not token_info:
        return "Token not available", 401
    return jsonify(token_info)

def start_server():
    app.run(port=8888, debug=False)

# 启动 Flask 服务器
threading.Thread(target=start_server).start()

# 等待用户完成 OAuth 流程
while not global_token_info:
    time.sleep(1)

token_info = get_token()
spotify = Spotify(auth=token_info['access_token'])

def check_and_play_next():
    try:
        playback = spotify.current_playback()
        if playback is None or not playback['is_playing']:
            spotify.start_playback()
            time.sleep(1)  # 等待播放开始
            spotify.next_track()
            logging.info("已开始播放并跳到下一首歌")
        else:
            logging.info("当前正在播放")
    except Exception as e:
        logging.error(f"检查播放状态时出错: {e}")


# 以下是 Kook 机器人的代码
@bot.command(name='play')
async def music_cmd(msg: Message, *args):
    if len(args) == 0:
        await msg.reply('请输入歌曲名称。')
        return
    song_name = ' '.join(args)  # 合并所有参数作为歌曲名称
    
    results = spotify.search(q=song_name, limit=1, type='track')
    tracks = results['tracks']['items']
    
    if tracks:
        track_uri = tracks[0]['uri']
        spotify.add_to_queue(track_uri)
        await msg.reply(f'已将 {tracks[0]["name"]} 添加到播放队列。')
        check_and_play_next()   #检查是否播放
    else:
        await msg.reply('未找到相关歌曲。')

@bot.command(name='next')
async def next_cmd(msg: Message):
    try:
        spotify.next_track()
        await msg.reply('已切到下一首歌。')
    except Exception as e:
        await msg.reply(f'切换下一首歌时出错: {e}')


@bot.command(name='pause')
async def pause_cmd(msg: Message):
    try:
        spotify.pause_playback()
        await msg.reply('已暂停播放。')
    except Exception as e:
        await msg.reply(f'暂停播放时出错: {e}')






#——————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
#@bot.on_event(EventTypes.JOINED_CHANNEL)
#async def player_update(b:Bot,event:Event):
    #channel = await b.fetch_public_channel(event.body['channel_id'])
    #user = await b.fetch_public_channel(event.body['user_id'])
    #await b.reply(player+'进入了'+channel)

#用户加入kook频道
@bot.on_event(EventTypes.JOINED_CHANNEL)
async def join_guild_send_event(b: Bot, e: Event):
    try:
        print("user join channel", e.body)  # 用户加入了服务器
        ch = await bot.client.fetch_public_channel("2506365885049703")  # 获取指定文字频道的对象
        # 发送信息
        user_id = e.body['user_id']
        channel_id = e.body['channel_id']
        async def get_user_info(user_id):
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bot {KOOKtoken}',
                }
                async with session.get(f'https://www.kookapp.cn/api/v3/user/view?user_id={user_id}', headers=headers) as response:
                    if response.status == 200:
                        user_info = await response.json()
                        return user_info['data']['username']
                    else:
                        return None
        async def get_channel_info(channel_id):
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bot {KOOKtoken}',
                }
                async with session.get(f'https://www.kookapp.cn/api/v3/channel/view?target_id={channel_id}', headers=headers) as response:
                    if response.status == 200:
                        channel_info = await response.json()
                        return channel_info['data']['name']
                    else:
                        return None
        nickname = await get_user_info(user_id)
        channelname = await get_channel_info(channel_id)
        ret = await ch.send(nickname+"加入"+channelname) 
        print(f"ch.send | msg_id {ret['msg_id']}")  # 刚刚发送消息的id
    except Exception as result:
        print(traceback.format_exc())  # 打印报错详细信息














#——————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
#21点小游戏
#初始化
players = []
dealer = None
game_started = False
deck = []
current_bets = {}
current_actions = {}
player_data = {}
current_player_index = 1

# 定义扑克牌和玩家类
suits = ['红心', '方块', '梅花', '黑桃']
ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
values = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'J': 10, 'Q': 10, 'K': 10, 'A': 11}
deck = [suit + rank for suit in suits for rank in ranks]

class Player:
    def __init__(self, name):
        self.name = name
        self.hand = []
        self.balance = 1000
        self.bet = 0
    
    def reset_hand(self):
        self.hand = []
        self.bet = 0

# 定义辅助函数
def deal_card(deck):
    card = random.choice(deck)
    deck.remove(card)
    return card

def calculate_hand_value(hand):
    value = sum(values[card[-1]] for card in hand)
    num_aces = sum(card.startswith('A') for card in hand)
    while value > 21 and num_aces:
        value -= 10
        num_aces -= 1
    return value

def show_hand(hand, hidden=False):
    if hidden:
        return '[隐藏], ' + ', '.join(hand[1:])
    return ', '.join(hand)

# 游戏初始化和重置函数
async def initialize_game(num_players,event: Message):
    global players, dealer, game_started, deck, player_data
    deck = [suit + rank for suit in suits for rank in ranks]
    players = [Player(f"Player {i+1}") for i in range(num_players)]
    #await event.reply(players = [Player(input(f"输入Player{i + 1}的名称: ")) for i in range(num_players)])
    dealer = Player("庄家")
    game_started = True
    player_data = {player.name: {'state': 'betting', 'object': player} for player in players}

async def reset_game():
    global game_started, deck, player_data
    deck = [suit + rank for suit in suits for rank in ranks]
    for player in players:
        player.reset_hand()
    dealer.reset_hand()
    game_started = False
    player_data = {}

# 玩家下注和处理玩家操作的函数
async def place_bets(event: Message):
    for player in players:
        player_data[player.name]['state'] = 'betting'
        await event.reply(f"{player.name}, 你的资产有{player.balance}点. 输入你的押注 /bet <金额>:")

async def handle_bet(event: Message, player_name: str, bet: int):
    player = player_data[player_name]['object']
    if 0 < bet <= player.balance:
        player.bet = bet
        player.balance -= bet
        await event.reply(f"{player.name}下注了{bet}点.")
        player_data[player_name]['state'] = 'bet_placed'
        if all(data['state'] == 'bet_placed' for data in player_data.values()):
            await deal_initial_cards(event)
            await player_turn(players[0], event)
    else:
        await event.reply(f"无效的投注金额. 你拥有{player.balance}点资产.")

async def deal_initial_cards(event: Message):
    for _ in range(2):
        for player in players:
            player.hand.append(deal_card(deck))
        dealer.hand.append(deal_card(deck))
    await event.reply(f"\n庄家的手牌: {show_hand(dealer.hand, hidden=True)}")
    for player in players:
        await event.reply(f"{player.name}的手牌: {show_hand(player.hand)}")

async def player_turn(player, event: Message):
    player_data[player.name]['state'] = 'waiting_for_action'
    await event.reply(f"{player.name}, 选择操作: 拿牌(h)it, 停牌(s)tand, 加倍(d)ouble down, 分牌s(p)lit 使用 /ac <h/s/d/p>:")

async def handle_action(event: Message, player_name: str, action: str):
    global current_player_index  
    player = player_data[player_name]['object']
    if action == 'h':
        player.hand.append(deal_card(deck))
        await event.reply(f"{player.name}的手牌: {show_hand(player.hand)}")
        if calculate_hand_value(player.hand) > 21:
            await event.reply(f"{player.name}爆牌！ {calculate_hand_value(player.hand)}点.")
            player_data[player.name]['state'] = 'busted'
            current_player_index += 1
    elif action == 's':
        player_data[player_name]['state'] = 'stand'
        current_player_index += 1
    elif action == 'd':
        if player.balance >= player.bet:
            player.balance -= player.bet
            player.bet *= 2
            player.hand.append(deal_card(deck))
            await event.reply(f"{player.name}的手牌: {show_hand(player.hand)}")
            if calculate_hand_value(player.hand) > 21:
                await event.reply(f"{player.name}爆牌！ {calculate_hand_value(player.hand)}点.")
            player_data[player_name]['state'] = 'double_down'
            current_player_index += 1
        else:
            await event.reply("没有足够的资金来加倍.")
    elif action == 'p':
        if len(player.hand) == 2 and player.hand[0].split(' ')[0] == player.hand[1].split(' ')[0]:
            second_hand = [player.hand.pop()]
            player.hand.append(deal_card(deck))
            second_hand.append(deal_card(deck))
            await event.reply(f"{player.name}的第一张手牌: {show_hand(player.hand)}")
            await event.reply(f"{player.name}的第二张手牌: {show_hand(second_hand)}")
            players.append(Player(f"{player.name} (Split Hand)"))
            players[-1].hand = second_hand
            players[-1].bet = player.bet
            players[-1].balance = player.balance
            player_data[players[-1].name] = {'state': 'bet_placed', 'object': players[-1]}
            current_player_index += 1
        else:
            await event.reply("你的手牌不能分牌.")
    if current_player_index < len(players):
        await player_turn(players[current_player_index], event)
    else:
        await dealer_turn(event)

async def dealer_turn(event: Message):
    await event.reply(f"\n庄家的手牌: {show_hand(dealer.hand)}")
    while calculate_hand_value(dealer.hand) < 17:
        dealer.hand.append(deal_card(deck))
        await event.reply(f"庄家的手牌: {show_hand(dealer.hand)}")
    await calculate_results(event)

async def calculate_results(event: Message):
    dealer_value = calculate_hand_value(dealer.hand)
    if dealer_value > 21:
        await event.reply(f"庄家爆牌！ {dealer_value}点")
    for player in players:
        player_value = calculate_hand_value(player.hand)
        if player_value > 21:
            await event.reply(f"{player.name} 爆牌！并且输了赌注{player.bet}点.")
        elif dealer_value > 21 or player_value > dealer_value:
            winnings = player.bet * 2
            player.balance += winnings
            await event.reply(f"{player.name} 获胜！{player_value}点.并且赢得了赌注{winnings}点.")
        elif player_value == dealer_value:
            player.balance += player.bet
            await event.reply(f"{player.name} 平局. {player_value}点.并且返还了赌注{player.bet}点.")
        else:
            await event.reply(f"{player.name} 输了！{player_value}点.并且失去了资金{player.bet}点.")
    await reset_game()
    await event.reply("Game over.")

# 机器人命令处理
@bot.command(name='开始21点')
async def start_game(event: Message, num_players: int):
    global game_started
    if game_started:
        await event.reply("游戏进程已经存在.")
    else:
        await initialize_game(num_players,event)
        await place_bets(event)

@bot.command(name='结束21点')
async def end_game(event: Message):
    global game_started
    if game_started:
        await reset_game()
        await event.reply("游戏结束.")
    else:
        await event.reply("游戏进程不存在.")

@bot.command(name='bet')
async def bet(event: Message, amount: int):
    player_name = next((p.name for p in players if player_data.get(p.name)['state'] == 'betting'), None)
    if player_name:
        await handle_bet(event, player_name, amount)

@bot.command(name='ac')
async def action(event: Message, action: str):
    player_name = next((p.name for p in players if player_data.get(p.name)['state'] == 'waiting_for_action'), None)
    if player_name:
        await handle_action(event, player_name, action)




























bot.run()
#机器人下线
@bot.command(name='下线')
async def offline():
    await bot.client.offline()

#print(channel)
#print(user)


#PyOfficeRobot.chat.send_message(who='不许用kook', message='player进入服务器'+ channel)