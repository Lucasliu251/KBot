import aiohttp
import asyncio

async def get_lyric(song):
    search_url = "http://music.163.com/api/search/pc"
    song_url_template = "http://music.163.com/api/song/media?id={}"
    
    # 搜索歌曲
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
        
        # 获取歌词
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

# 测试异步函数
async def main():
    lyric = await get_lyric('搁浅')
    print(lyric)

# 运行测试
asyncio.run(main())
