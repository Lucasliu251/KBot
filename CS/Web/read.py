import json

def generate_option_from_json(file_path):
    # 读取 JSON 文件
    with open(file_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)

    # 初始化数据集
    dataset = {
        'source': [['date']],  # 第一行是列名，开始只包含日期列
        'xAxis': {'type': 'category'},
        'yAxis': {},
        'series': []
    }

    # 提取所有的日期和玩家名称
    dates = list(json_data.keys())
    player_names = set()

    for date in dates:
        player_names.update(json_data[date].keys())

    # 将玩家名称添加到 dataset.source 的第一行
    dataset['source'][0].extend(player_names)

    # 为每个玩家添加一列到 series 中
    dataset['series'] = [{'type': 'line'} for _ in player_names]

    # 遍历 jsonData，构建每一天的数据
    for date in dates:
        new_row = [date]  # 新的一行，第一列是日期
        for player in player_names:
            # 获取该玩家在该日期的击杀数，如果没有数据则填充0
            kills = json_data[date].get(player, {}).get('今日击杀数', 0)
            new_row.append(kills)
        # 将新行添加到 dataset.source 中
        dataset['source'].append(new_row)

    return dataset

# 使用示例
file_path = 'D:/Develop/project/KBot/CS/data/dirt.json'
option = generate_option_from_json(file_path)
print(json.dumps(option, ensure_ascii=False, indent=2))
