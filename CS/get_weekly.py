# import schedule
import time
import os
import pandas as pd
import configparser
from datetime import datetime, timedelta

data = [] 

folder_path = "/CS/data"  # 文件夹路径
start_date = datetime.now().strftime('%Y-%m-%d')  # 开始日期

def load_config():
    config = configparser.ConfigParser()
    with open('C:/Users/Administrator/Desktop/KooK_Bot/CS/config.ini', 'r', encoding='utf-8') as f:
        config.read_file(f)
    return config

def weekly_task(dataframe, nicknames_to_ids, start_date, folder_path):
    start_date = datetime.strptime(start_date, "%Y-%m-%d")
    previous_stats = {}
    for i in range(7):  # 遍历过去7天
        print(f"第{i+1}天")
        target_date = start_date - timedelta(days=i)
        file_name = f"player_stats_{target_date.strftime('%Y-%m-%d')}.txt"
        file_path = os.path.join(folder_path, file_name)
        print(f"正在读取文件：{file_path}")

        if os.path.exists(file_path):
            print(f"文件是否存在：{os.path.exists(file_path)}")
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f.readlines()[1:]:  # 跳过标题行
                    parts = line.split()
                    nickname = parts[1]
                    kills = int(parts[4])
                    deaths = int(parts[5])
                    headshot = int(parts[7])
                    damage = int(parts[11])
                    mvp = int(parts[13])

                    steam_id = nicknames_to_ids.get(nickname)
                    if steam_id:
                        # 如果 SteamID 不在 previous_stats 中，初始化
                        if steam_id not in previous_stats:
                            previous_stats[steam_id] = {'Kills': 0, 'Deaths': 0, 'Headshot': 0, 'Damage': 0, 'MVP': 0}
                        
                        # 正确累加数据
                        previous_stats[steam_id]['Kills'] += kills
                        previous_stats[steam_id]['Deaths'] += deaths
                        previous_stats[steam_id]['Headshot'] += headshot
                        previous_stats[steam_id]['Damage'] += damage
                        previous_stats[steam_id]['MVP'] += mvp

    # 更新 DataFrame
    for steam_id, stats in previous_stats.items():
        dataframe.loc[dataframe['SteamID'] == steam_id, 'Kills'] += stats['Kills']
        dataframe.loc[dataframe['SteamID'] == steam_id, 'Deaths'] += stats['Deaths']
        dataframe.loc[dataframe['SteamID'] == steam_id, 'Headshot'] += stats['Headshot']
        dataframe.loc[dataframe['SteamID'] == steam_id, 'Damage'] += stats['Damage']
        dataframe.loc[dataframe['SteamID'] == steam_id, 'MVP'] += stats['MVP']

    return dataframe

    


def main():
    config = load_config()
    steam_ids = []
    nicknames_to_ids = {}
    for key, value in config['SteamIDs'].items():
        steam_id, nickname = value.split('#')[0].strip(), value.split('#')[1].strip()
        steam_ids.append(steam_id)
        nicknames_to_ids[nickname] = steam_id

    # 初始化数据
    data = [
        {'Player': nickname, 'SteamID': steam_id, 'Kills': 0, 'Deaths': 0, 'Damage': 0, 'Headshot': 0, 'K/D': 0.0, 'HS%': 0, 'MVP': 0}
        for nickname, steam_id in nicknames_to_ids.items()
    ]
    df = pd.DataFrame(data)
    weekly_data = weekly_task(df, nicknames_to_ids, start_date, folder_path)
    print("一周内的数据：")
    print(weekly_data)

    # 步骤1：归一化处理
    for col in ['Kills', 'Deaths', 'Damage', 'K/D', 'HS%', 'MVP']:
        max_val = weekly_data[col].max()
        if max_val == 0:
            max_val = 1  # 避免除以 0
        weekly_data[col] = weekly_data[col] / max_val

    # 打印调试信息
    print("归一化后的数据：")
    print(weekly_data)

    # 步骤2：加权计算
    weekly_data['Score'] = (
        0.25 * weekly_data['Kills'] -  # 击杀
        0.1 * weekly_data['Deaths'] +  # 死亡数（负权重）
        0.2 * weekly_data['Damage'] +  # 伤害
        0.2 * weekly_data['K/D'] +     # K/D
        0.15 * weekly_data['HS%'] +    # 爆头率
        0.1 * weekly_data['MVP']       # MVP 次数
    )

    # 步骤3：检查是否有 NaN
    if weekly_data['Score'].isna().any():
        print("警告：计算的 Score 列存在 NaN 值。请检查数据输入是否正确。")
        print(weekly_data[['Player', 'Score']])
        return

    # 步骤4：找出最高分的玩家
    fmvp = weekly_data.loc[weekly_data['Score'].idxmax()]

    # 输出结果
    print("本周FMVP是：", fmvp['Player'])
    print("详细数据：\n", fmvp)


    


    # schedule.every().saturday.at("20:00").do(weekly_task)
    # print("定时程序正在运行。等待任务...")

    # while True:
    #     schedule.run_pending()
    #     time.sleep(50)  # 避免CPU占用过高

if __name__ == "__main__":
    main()
