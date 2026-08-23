import configparser
import os
import requests
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import pandas as pd
from pathlib import Path

CS_DIR = Path(__file__).resolve().parent
DATA_DIR = CS_DIR / 'data'




def load_config():
    config = configparser.ConfigParser()
    # 建议使用相对路径或确保路径正确
    config_path = CS_DIR / 'config.ini'
        
    with open(config_path, 'r', encoding='utf-8') as f:
        config.read_file(f)
    return config

def get_player_stats(api_key, steam_id):
    """请求 Steam API"""
    url = f'http://api.steampowered.com/ISteamUserStats/GetUserStatsForGame/v2/?key={api_key}&steamid={steam_id}&appid=730'
    try:
        response = requests.get(url, timeout=10) # 添加超时防止卡死
        if response.status_code == 200:
            return response.json()
        else:
            print(f"无法获取SteamID {steam_id} 的数据 (Status: {response.status_code})")
            return None
    except Exception as e:
        print(f"请求 SteamID {steam_id} 失败: {e}")
        return None
    



def process_player_stats(stats):
    """
    [优化] 解析 API 数据，返回字典格式，包含新增字段
    """
    # 初始化所有需要的字段为 0
    data = {
        'total_kills': 0,
        'total_deaths': 0,
        'total_HS': 0, # 对应 total_kills_headshot
        'total_damage': 0,    # 对应 total_damage_done
        'total_mvps': 0,
        # --- 新增字段 ---
        'total_wins': 0,
        'total_rounds_played': 0,    # 对应 total_rounds_played
        'total_time_played': 0,
        'total_money_earned': 0,
    }
    
    # Steam API 的字段名映射
    key_mapping = {
        'total_kills': 'total_kills',
        'total_deaths': 'total_deaths',
        'total_kills_headshot': 'total_HS',
        'total_damage_done': 'total_damage',
        'total_mvps': 'total_mvps',
        'total_wins': 'total_wins',
        'total_rounds_played': 'total_rounds_played',
        'total_time_played': 'total_time_played',
        'total_money_earned': 'total_money_earned',
    }

    if 'playerstats' in stats and 'stats' in stats['playerstats']:
        for stat in stats['playerstats']['stats']:
            name = stat['name']
            if name in key_mapping:
                # 将 API 的值填入 data 字典对应的 key 中
                data[key_mapping[name]] = stat['value']
                
    return data

def read_previous_day_stats(file_path, nicknames_to_ids):
    """
    读取前一天的 TXT 文件用于计算增量 (保持原有逻辑以兼容 TXT 格式)
    """
    previous_stats = {}
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if len(lines) > 1:
                    for line in lines[1:]:  # 跳过标题行
                        parts = line.split()
                        if len(parts) < 13: continue # 简单校验防止越界
                        
                        nickname = parts[1]
                        kills = int(parts[2])
                        deaths = int(parts[3])
                        # 注意：这里严格依赖 TXT 的列顺序
                        headshot = int(parts[7])
                        damage = int(parts[10])
                        mvp = int(parts[12])
                        
                        steam_id = nicknames_to_ids.get(nickname)
                        if steam_id:
                            previous_stats[steam_id] = {
                                'kills': kills, 'deaths': deaths, 
                                'headshots': headshot, 'damage': damage, 'mvp': mvp
                            }
        except Exception as e:
            print(f"读取昨日数据出错: {e}")
            
    return previous_stats

def save_today_stats(output_file, player_data_list):
    """
    保存 TXT 文件 (保持原有格式不变)
    player_data_list 里的元素现在是字典，需要适配
    """
    output = []
    # 标题行 (保持不变)
    output.append(f"{'Rank'.ljust(6)}{'Nickname'.ljust(30)}{'今日击杀数'.ljust(20)}{'今日死亡数'.ljust(20)}{'新增击杀数'.ljust(20)}{'新增死亡数'.ljust(20)}{'击杀比'.ljust(6)}{'今日爆头数'.ljust(20)}{'新增爆头数'.ljust(20)}{'爆头率'.ljust(6)}{'今日伤害量'.ljust(20)}{'新增伤害量'.ljust(20)}{'今日MVP次数'.ljust(20)}{'新增MVP次数'.ljust(20)}")
    
    for i, p in enumerate(player_data_list, start=1):
        line = (
            f"Top{str(i):<5}"
            f"{p['nickname'].ljust(30)}"
            f"{str(p['total_kills']).ljust(20)}"
            f"{str(p['total_deaths']).ljust(20)}"
            f"{str(p['new_kills']).ljust(20)}"
            f"{str(p['new_deaths']).ljust(20)}"
            f"{str(p['KD']).ljust(6)}"
            f"{str(p['total_HS']).ljust(20)}"
            f"{str(p['new_headshots']).ljust(20)}"
            f"{str(p['HS']).ljust(6)}"
            f"{str(p['total_damage']).ljust(20)}"
            f"{str(p['new_damage']).ljust(20)}"
            f"{str(p['total_mvps']).ljust(20)}"
            f"{str(p['new_mvps']).ljust(20)}"
        )
        output.append(line)
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for line in output:
            f.write(line + '\n')

def save_to_sql(player_data_list, record_date, DB_URI):
    """
    将当日最新 Totals 写入 PostgreSQL daily 表。
    同一天重复跑时先删后插，避免 uk_user_date 唯一约束冲突。

    @param player_data_list: 含 steam_id / nickname / 累计统计的玩家字典列表
    @param record_date: 记录日期，YYYY-MM-DD
    @param DB_URI: SQLAlchemy 连接串
    @returns: None

    @changelog
    - 2026-08-22: 改为 PostgreSQL；按 record_date 先删后插 (Author: KBot)
    """
    try:
        engine = create_engine(DB_URI)
        
        # 准备要插入的数据列表 (只包含数据库需要的字段)
        db_records = []
        for p in player_data_list:
            db_records.append({
                "steam_id": p['steam_id'],
                "nickname": p['nickname'],
                "record_date": record_date,
                "total_kills": p['total_kills'],
                "total_deaths": p['total_deaths'],
                "total_damage": p['total_damage'],
                "total_rounds_played": p['total_rounds_played'], # 新增
                "total_wins": p['total_wins'],     # 新增
                "total_mvps": p['total_mvps'],
                "total_HS": p['total_HS'],
                "total_time_played": p['total_time_played'], # 新增
                "total_money_earned": p['total_money_earned'] 
            })
            
        if not db_records: return

        df = pd.DataFrame(db_records)
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM daily WHERE record_date = :record_date"),
                {"record_date": record_date},
            )
            df.to_sql('daily', conn, if_exists='append', index=False)
        print("✅ 数据库同步完成")
                
    except Exception as e:
        print(f"连接数据库失败: {e}")

def main():
    # ================= 配置区域 =================
    config = load_config()
    API_KEY = config['Steam']['API_KEY']
    DB_URI = config['SQL']['DB_URI']
    # ===========================================
    steam_ids = []
    nicknames_to_ids = {}
    for key, value in config['SteamIDs'].items():
        # 容错处理 split
        parts = value.split('#')
        if len(parts) >= 2:
            steam_id, nickname = parts[0].strip(), parts[1].strip()
            steam_ids.append(steam_id)
            nicknames_to_ids[nickname] = steam_id

    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    output_file = DATA_DIR / f"player_stats_{today}.txt"
    previous_file = DATA_DIR / f"player_stats_{yesterday}.txt"
    
    # 1. 读取昨日数据 (为了计算增量给 TXT 用)
    previous_day_stats = read_previous_day_stats(previous_file, nicknames_to_ids)
    
    final_player_data = []
    
    for steam_id in steam_ids:
        # 2. 获取 API 数据
        stats = get_player_stats(API_KEY, steam_id)
        if stats:
            print(f"{today} 数据收集中: {steam_id}")
            
            # 获取处理后的字典数据 (包含新老字段)
            current_data = process_player_stats(stats)
            
            # 获取昨日数据 (如果没找到，默认为 0)
            prev = previous_day_stats.get(steam_id, {'kills':0, 'deaths':0, 'headshots':0, 'damage':0, 'mvp':0})
            
            # 3. 计算增量 (用于 TXT 显示)
            new_kills = current_data['total_kills'] - prev['kills']
            new_deaths = current_data['total_deaths'] - prev['deaths']
            new_headshot = current_data['total_HS'] - prev['headshots']
            new_damage = current_data['total_damage'] - prev['damage']
            new_mvp = current_data['total_mvps'] - prev['mvp']
            
            # 计算比率
            kd_val = new_kills / new_deaths if new_deaths != 0 else 0
            KD = "{:.2f}".format(kd_val)
            
            hs_val = new_headshot / new_kills if new_kills != 0 else 0
            HS = "{:.0f}%".format(hs_val * 100)
            
            # 查找昵称
            nickname = "Unknown"
            for name, sid in nicknames_to_ids.items():
                if sid == steam_id:
                    nickname = name
                    break
            
            # 4. 组装整合数据对象 (便于传参)
            player_record = {
                'steam_id': steam_id,
                'nickname': nickname,
                # 核心 Total (存数据库用)
                **current_data, 
                # 增量与比率 (存 TXT 用)
                'new_kills': new_kills,
                'new_deaths': new_deaths,
                'new_headshots': new_headshot,
                'new_damage': new_damage,
                'new_mvps': new_mvp,
                'KD': KD,
                'HS': HS,
                # 用于排序的数值型 KD (因为 TXT 里的 KD 是字符串)
                'sort_kd': kd_val 
            }
            
            final_player_data.append(player_record)
    
    # 5. 排序 (按今日 KD 倒序)
    final_player_data.sort(key=lambda x: x['sort_kd'], reverse=True)

    # 6. 保存到 SQL 数据库
    save_to_sql(final_player_data, today, DB_URI)
    
    # 7. 保存到 TXT 文件 (保持旧格式)
    save_today_stats(output_file, final_player_data)
    print(f"处理完成，文件已生成: {output_file}")

if __name__ == "__main__":
    main()
