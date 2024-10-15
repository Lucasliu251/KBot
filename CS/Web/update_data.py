import json
import os
from datetime import datetime

# 读取TXT文件内容
def read_txt_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
    return lines

# 转换为JSON格式
def convert_to_json(lines, date_str):
    data = {}  # 直接初始化空字典
    players = {}  # 用于存储每个玩家的数据
    
    for line in lines[1:]:  # 跳过标题行
        parts = line.split()
        if len(parts) >= 3:  # 至少有 Nickname 和 今日击杀数
            nickname = parts[1]
            players[nickname] = {
                "今日击杀数": int(parts[2])
            }
            if len(parts) == 4:  # 如果只有4列，则输出新增击杀数
                players[nickname]["新增击杀数"] = int(parts[3])
            elif len(parts) >= 5:  # 如果有5列或更多，先输出今日死亡数，再输出其他
                players[nickname]["今日死亡数"] = int(parts[3])
                players[nickname]["新增击杀数"] = int(parts[4])
                if len(parts) >= 6:
                    players[nickname]["新增死亡数"] = int(parts[5])
                if len(parts) >= 7:
                    players[nickname]["击杀比"] = float(parts[6])
            
            data[date_str] = players

    return data  


# 合并新的数据到现有的JSON文件
def update_json_file(new_data, json_file_path):
    if os.path.exists(json_file_path):
        with open(json_file_path, 'r', encoding='utf-8') as file:
            existing_data = json.load(file)
    else:
        existing_data = {}  # 初始化为空字典

    # 获取新数据中的日期
    new_date = list(new_data.keys())[0]  # 假设 new_data 只有一个日期键
    
    # 如果现有数据中存在相同日期的数据，先删除旧数据
    if new_date in existing_data:
        del existing_data[new_date]

    # 合并新数据到现有数据，保留日期键
    existing_data.update(new_data)
    
    with open(json_file_path, 'w', encoding='utf-8') as file:
        json.dump(existing_data, file, ensure_ascii=False, indent=4)


# 主程序
def process_files(input_directory, json_file_path):
    for filename in os.listdir(input_directory):
        if filename.startswith('player_stats_') and filename.endswith('.txt'):
            file_path = os.path.join(input_directory, filename)
            print(f"正在处理文件: {filename}")
            # 通过下划线分割文件名并提取日期部分
            date_str = filename.split('_')[2].replace('.txt', '')  # 提取日期
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')  # 确保日期格式正确
            formatted_date = date_obj.strftime('%Y-%m-%d')
            
            # 处理每个TXT文件的数据
            lines = read_txt_file(file_path)
            new_data = convert_to_json(lines, formatted_date)
            update_json_file(new_data, json_file_path)
# 配置路径
input_directory = 'C:/Users/Administrator/Desktop/KooK_Bot/CS/data'  # 替换为存放TXT文件的目录
json_file_path = 'C:/Users/Administrator/Desktop/KooK_Bot/CS/data/dirt.json'  # 替换为你要保存的JSON文件路径

process_files(input_directory, json_file_path)
