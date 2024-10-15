import subprocess
import asyncio
import aiohttp
from khl import *

bot_token = '1/MzI4MDU=/k7tU+d3eOpsPrF5H1TK9Ug=='
bot = Bot(token=bot_token)




# 假设你有一个 bot 对象来管理KOOK API调用
async def play_audio_in_channel(vcid,audio_file):
    
    data = await join_channel(vcid)
    
    ip = data['ip']
    port = data['port']
    rtcp_port = data['rtcp_port']
    ssrc = data['audio_ssrc']
    payload_type = data['audio_pt']
    bitrate = data['bitrate']
    rtcp_mux = data['rtcp_mux']

    # 构造 FFmpeg 推流命令
    ffmpeg_command = [
        "ffmpeg", 
        "-re",
        "-i", audio_file,
        "-map", "0:a:0",
        "-acodec", "libopus", 
        "-ab", f"{bitrate}", 
        "-ac", "1", 
        "-ar", "48000", 
        "-f", "tee",
        f'[select=a:f=rtp:ssrc={ssrc}:payload_type={payload_type}]rtp://{ip}:{port}?rtcpport={rtcp_port}'
    ]

    if rtcp_mux:
        ffmpeg_command.append("?rtcp_mux=true")

    # 通过 subprocess 模块执行 FFmpeg 推流命令
    subprocess.run(ffmpeg_command)
    await leave_channel(vcid)#退出频道



# API请求信息
async def find_user(gid, aid):
    # 调用接口查询用户所在的语音频道
    voice_channel_ = await bot.client.gate.request('GET', 'channel-user/get-joined-channel',
                                                    params={'guild_id': gid, 'user_id': aid})
    voice_channel = voice_channel_["items"]
    if voice_channel:
        vcid = voice_channel[0]['id']
        return vcid


async def get_user_roles(user_id):
    async with aiohttp.ClientSession() as session:
        headers = {
            'Authorization': f'Bot {bot_token}',
        }
        async with session.get(f'https://www.kookapp.cn/api/v3/user/view?user_id={user_id}', headers=headers) as response:
            if response.status == 200:
                user_info = await response.json()
                return user_info['data']['bot']  # 返回用户的角色ID列表
            else:
                return None
            
async def join_channel(vcid):
        # 通过 /api/v3/voice/join 接口加入语音频道，获取推流IP和端口
        headers = {
            'Authorization': f'Bot {bot_token}',  # 传入 KOOK 机器人 token
            'Content-Type': 'application/json'  # 指定请求体的格式
        }
        data = {
            'channel_id': vcid  # 语音频道的 ID
        }

        async with aiohttp.ClientSession() as session:
            async with session.post('https://www.kookapp.cn/api/v3/voice/join', headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    if result['code'] == 0:
                       # 成功加入语音频道，返回推流 IP 和端口等信息
                        return result['data']
                    else:
                        print(f"加入失败: {result['message']} (错误码: {result['code']})")
                        return None
                else:
                    print(f"请求失败: {response.status}")
                    return None
                
async def leave_channel(vcid):
        # 通过 /api/v3/voice/join 接口加入语音频道，获取推流IP和端口
        headers = {
            'Authorization': f'Bot {bot_token}',  # 传入 KOOK 机器人 token
            'Content-Type': 'application/json'  # 指定请求体的格式
        }
        data = {
            'channel_id': vcid  # 语音频道的 ID
        }

        async with aiohttp.ClientSession() as session:
            async with session.post('https://www.kookapp.cn//api/v3/voice/leave', headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    if result['code'] == 0:
                       # 成功加入语音频道，返回推流 IP 和端口等信息
                        return result['data']
                    else:
                        print(f"退出失败: {result['message']} (错误码: {result['code']})")
                        return None
                else:
                    print(f"请求失败: {response.status}")
                    return None
            

#用户加入kook频道
@bot.on_event(EventTypes.JOINED_CHANNEL)
async def join_guild_send_event(b: Bot, e: Event):
    # 读取信息
    user_id = e.body['user_id']
    #print(user_id)
    roles = await get_user_roles(user_id)
    # 检查用户是否为机器人
    if roles:  # 如果用户为"机器人"
        print(f"用户 {user_id} 是机器人，跳过通知")
        return
    
    channel_id = e.body['channel_id']
    if user_id in whitelist:
        audio_file = f"C:/Users/Administrator/Desktop/KooK_Bot/broadcast/音效库/{whitelist[user_id]}"

        #Bot加入语音频道并播放
        await play_audio_in_channel(channel_id,audio_file)
    else:
        print(f"用户 {user_id} 不在白名单中，跳过播放。")
    
    


#手动播放
@bot.command(name='playtest')
async def play_sound(msg: Message):
# 获取用户所在的语音频道
    channel_id = await find_user(msg.ctx.guild.id, msg.author_id)
    if channel_id is None:
        await msg.ctx.channel.send('请先加入语音频道')
        return
     
    audio_file = "C:/Users/Administrator/Desktop/KooK_Bot/broadcast/音效库/肛门.mp3"
    await play_audio_in_channel(channel_id,audio_file)


    


#音效白名单
whitelist = {
    "3165176953": "涛哥涛哥涛涛.mp3",
    "190616984": "逼哥逼哥.mp3",
    "1474281407": "肛门.mp3",
    #"2664110832": "肛门.mp3"
}

if __name__ == '__main__':
    bot.run()