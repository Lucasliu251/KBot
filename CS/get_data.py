import configparser
import os
import requests
from datetime import datetime, timedelta


def load_config():
    config = configparser.ConfigParser()
    with open('C:/Users/Administrator/Desktop/KooK_Bot/CS/config.ini', 'r', encoding='utf-8') as f:
        config.read_file(f)
    return config

def get_player_stats(api_key, steam_id):
    url = f'http://api.steampowered.com/ISteamUserStats/GetUserStatsForGame/v2/?key={api_key}&steamid={steam_id}&appid=730'
    response = requests.get(url, timeout=10)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"无法获取SteamID {steam_id} 的数据")
        return None

def process_player_stats(stats):
    total_kills = 0
    total_deaths = 0
    total_headshot = 0
    total_damage = 0
    total_mvp = 0
    
    for stat in stats['playerstats']['stats']:
        if stat['name'] == 'total_kills':
            total_kills = stat['value']
        if stat['name'] == 'total_deaths':
            total_deaths = stat['value']
        if stat['name'] == 'total_kills_headshot':
            total_headshot = stat['value']
        if stat['name'] == 'total_damage_done':
            total_damage = stat['value']
        if stat['name'] == 'total_mvps':
            total_mvp = stat['value']
    return total_kills,total_deaths,total_headshot,total_damage,total_mvp


def read_previous_day_stats(file_path,nicknames_to_ids):
    previous_stats = {}
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f.readlines()[1:]:  # 跳过标题行
                parts = line.split()
                nickname = parts[1]
                kills = int(parts[2])
                deaths = int(parts[3])
                headshot = int(parts[7])
                damage = int(parts[10])
                mvp = int(parts[12])
                steam_id = nicknames_to_ids.get(nickname)
                if steam_id:
                    previous_stats[steam_id] = kills,deaths,headshot,damage,mvp
    return previous_stats

def save_today_stats(output_file, player_data):
    output = []
    output.append(f"{'Rank'.ljust(6)}{'Nickname'.ljust(30)}{'今日击杀数'.ljust(20)}{'今日死亡数'.ljust(20)}{'新增击杀数'.ljust(20)}{'新增死亡数'.ljust(20)}{'击杀比'.ljust(6)}{'今日爆头数'.ljust(20)}{'新增爆头数'.ljust(20)}{'爆头率'.ljust(6)}{'今日伤害量'.ljust(20)}{'新增伤害量'.ljust(20)}{'今日MVP次数'.ljust(20)}{'新增MVP次数'.ljust(20)}")
    for i, (steam_id, nickname, total_kills, total_deaths, new_kills, new_deaths, KD, total_headshot, new_headshot, HS, total_damage, new_damage, total_mvp, new_mvp) in enumerate(player_data, start=1):
        output.append(f"Top{i:<5}{nickname.ljust(30)}{str(total_kills).ljust(20)}{str(total_deaths).ljust(20)}{str(new_kills).ljust(20)}{str(new_deaths).ljust(20)}{str(KD).ljust(6)}{str(total_headshot).ljust(20)}{str(new_headshot).ljust(20)}{str(HS).ljust(6)}{str(total_damage).ljust(20)}{str(new_damage).ljust(20)}{str(total_mvp).ljust(20)}{str(new_mvp).ljust(20)}")
    
    if not os.path.exists("CS/data"):
        os.makedirs("CS/data")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for line in output:
            f.write(line + '\n')



def main():
    config = load_config()
    API_KEY = config['Steam']['API_KEY']
    steam_ids = []
    nicknames_to_ids = {}
    for key, value in config['SteamIDs'].items():
        steam_id, nickname = value.split('#')[0].strip(), value.split('#')[1].strip()
        steam_ids.append(steam_id)
        nicknames_to_ids[nickname] = steam_id

    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    output_file = os.path.join("CS/data", f"player_stats_{today}.txt")
    previous_file = os.path.join("CS/data", f"player_stats_{yesterday}.txt")
    
    previous_day_stats = read_previous_day_stats(previous_file, nicknames_to_ids)
    
    player_data = []
    for steam_id in steam_ids:
        stats = get_player_stats(API_KEY, steam_id)
        if stats:
            print(today+'数据收集中')

            total_kills, total_deaths, total_headshot, total_damage, total_mvp= process_player_stats(stats)
            previous_kills, previous_deaths, previous_headshot, previous_damage, previous_mvp = previous_day_stats.get(steam_id, (0, 0, 0, 0, 0))
            new_kills = total_kills - previous_kills
            new_deaths = total_deaths - previous_deaths
            new_headshot = total_headshot - previous_headshot
            new_damage = total_damage - previous_damage
            new_mvp = total_mvp - previous_mvp
            KD = new_kills / new_deaths if new_deaths != 0 else 0
            KD = "{:.2f}".format(KD)
            HS = new_headshot / new_kills if new_kills != 0 else 0
            HS = "{:.0f}%".format(HS * 100)
            
            nickname = None
            for name, id in nicknames_to_ids.items():
                if id == steam_id:
                    nickname = name
                    break
            player_data.append((steam_id, nickname, total_kills, total_deaths, new_kills, new_deaths, KD, total_headshot, new_headshot , HS, total_damage, new_damage, total_mvp, new_mvp))
    
    player_data.sort(key=lambda x: x[6], reverse=True)

    
    return save_today_stats(output_file, player_data)

if __name__ == "__main__":
    main()
