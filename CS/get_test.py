import configparser
import os
import requests
import json
from datetime import datetime,timedelta

# 读取config文件
config = configparser.ConfigParser()
with open('config.ini', 'r', encoding='utf-8') as f:
    config.read_file(f)

API_KEY = config['Steam']['API_KEY']
steam_ids = []
nicknames = {}
for key, value in config['SteamIDs'].items():
    steam_id, nickname = value.split('#')[0].strip(), value.split('#')[1].strip()  # 去除#号后面的内容并提取昵称
    steam_ids.append(steam_id)
    nicknames[steam_id] = nickname

# 创建数据保存文件夹（如果不存在）
data_folder = 'data'
if not os.path.exists(data_folder):
    os.makedirs(data_folder)

def get_player_stats(steam_id):
    url = f'http://api.steampowered.com/ISteamUserStats/GetUserStatsForGame/v2/?key={API_KEY}&steamid={steam_id}&appid=730'  # 730是CSGO的AppID
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"无法获取SteamID {steam_id} 的数据")
        return None

def process_player_stats(stats):
    kills = 0
    matches = 0
    wins = 0
    
    for stat in stats['playerstats']['stats']:
        if stat['name'] == 'total_kills':
            kills = stat['value']
        elif stat['name'] == 'total_matches_played':
            matches = stat['value']
        elif stat['name'] == 'total_wins':
            wins = stat['value']

    return kills, matches, wins

def read_previous_day_stats(file_path):
    previous_stats = {}
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f.readlines()[1:]:  # 跳过标题行
                parts = line.split()
                steam_id = parts[1]
                kills = int(parts[2])
                matches = int(parts[3])
                wins = int(parts[4])
                previous_stats[steam_id] = (kills, matches, wins)
    return previous_stats



# 获取当前日期和昨日日期
today = datetime.now().strftime('%Y-%m-%d')
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

# 文件名基于日期
output_file = f"player_stats_{today}.txt"
previous_file = f"player_stats_{yesterday}.txt"

# 读取昨日的击杀、局数、获胜数据
previous_day_stats = read_previous_day_stats(previous_file)



# 收集数据并排序
player_data = []
for steam_id in steam_ids:
    stats = get_player_stats(steam_id)
    if stats:
        kills, matches, wins = process_player_stats(stats)
        previous_kills, previous_matches, previous_wins = previous_day_stats.get(steam_id, (0, 0, 0))
        new_kills = kills - previous_kills
        new_matches = matches - previous_matches
        new_wins = wins - previous_wins
        player_data.append((steam_id, nicknames[steam_id], new_kills, new_matches, new_wins))

# 按新增击杀数降序排序
player_data.sort(key=lambda x: x[2], reverse=True)



# 打印前10名玩家数据
# 定义输出格式
output = []
output.append(f"{'Rank'.ljust(6)}{'Nickname'.ljust(15)}{'今日新增击杀数'.ljust(20)}{'今日新增局数'.ljust(20)}{'今日新增获胜数'.ljust(20)}")

for i, (steam_id, nickname, new_kills, new_matches, new_wins) in enumerate(player_data[:10], start=1):
    output.append(f"Top{i:<5}{nickname.ljust(15)}{str(new_kills).ljust(20)}{str(new_matches).ljust(20)}{str(new_wins).ljust(20)}")

# 打印到CMD
for line in output:
    print(line)

# 保存到txt文件
output_file = os.path.join("data", f"player_stats_{today}.txt")
with open(output_file, 'w', encoding='utf-8') as f:
    for line in output:
        f.write(line + '\n')

print(f"\n数据已导出到 {output_file}")


