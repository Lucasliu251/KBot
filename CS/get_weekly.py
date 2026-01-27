import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import pymysql


os.system('python CS/get_data.py')
# 手动输入日期
#input_date = input("请输入今天的日期 (YYYY-MM-DD): ")
# 将输入的日期字符串转换为 datetime 对象
#day = datetime.strptime(input_date, "%Y-%m-%d")
# 设置目标日期
today = datetime.now()

# 年、周数
year, week, _ = today.isocalendar()

# 生成过去7天的日期
date_list = [(datetime.strptime(today.strftime('%Y-%m-%d'), '%Y-%m-%d') - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
print(f"Week {year}-W{week}: {date_list}")

# 连接 MySQL 数据库
conn = pymysql.connect(
    host="47.115.75.168",          # 替换为 MySQL 主机地址
    user="KYD",      # 替换为用户名
    password="88888888",  # 替换为密码
    charset="utf8mb4",          # 确保支持 UTF-8 字符集
    database='trashbox'
)
cursor = conn.cursor()

# 初始化一个空的 DataFrame 用于累加数据
total_data = pd.DataFrame()

# 遍历7天的文件
for date in date_list:
    file_path = f'CS/data/player_stats_{date}.txt'


    # 读取文件
    data = pd.read_csv(file_path, sep=r'\s{2,}', engine='python',usecols=['Nickname', '新增击杀数', '新增死亡数', '新增爆头数', '新增伤害量', '新增MVP次数'])
    # 确保每一列的数据都是数字类型
    data['新增击杀数'] = pd.to_numeric(data['新增击杀数'], errors='coerce').fillna(0)
    data['新增死亡数'] = pd.to_numeric(data['新增死亡数'], errors='coerce').fillna(0)
    data['新增爆头数'] = pd.to_numeric(data['新增爆头数'], errors='coerce').fillna(0)
    data['新增伤害量'] = pd.to_numeric(data['新增伤害量'], errors='coerce').fillna(0)
    data['新增MVP次数'] = pd.to_numeric(data['新增MVP次数'], errors='coerce').fillna(0)
    # 遍历每一行（每个玩家），将数据累加到total_data
    if total_data.empty:
        total_data = data.copy()
    for index, row in data.iterrows():
        nickname = row['Nickname']
        if nickname in total_data['Nickname'].values:
            # 如果该玩家的数据已经存在，找到该玩家并累加数据
            total_data.loc[total_data['Nickname'] == nickname, '新增击杀数'] += row['新增击杀数']
            total_data.loc[total_data['Nickname'] == nickname, '新增死亡数'] += row['新增死亡数']
            total_data.loc[total_data['Nickname'] == nickname, '新增爆头数'] += row['新增爆头数']
            total_data.loc[total_data['Nickname'] == nickname, '新增伤害量'] += row['新增伤害量']
            total_data.loc[total_data['Nickname'] == nickname, '新增MVP次数'] += row['新增MVP次数']



# 设置每列的合理范围，剔除异常值
columns_to_clean = {
    '新增击杀数': (0, 2000),  # 假设合理范围是 0 到 2000
    '新增死亡数': (0, 2000),
    '新增爆头数': (0, 2000)
}
for column, (min_val, max_val) in columns_to_clean.items():
    total_data = total_data[(data[column] >= min_val) & (total_data[column] <= max_val)]



# 计算 K/D 和 HS 并保留两位小数
total_data['K/D'] = (total_data['新增击杀数'] / total_data['新增死亡数']).round(2)
total_data['HS'] = (total_data['新增爆头数'] / total_data['新增击杀数']).round(2)

# 在标准化之前，保存一份原始数据
original_data = pd.DataFrame()
original_data = total_data.copy()


# 标准化处理
total_data['新增击杀数'] = total_data['新增击杀数'] / total_data['新增击杀数'].mean()
total_data['新增死亡数'] = total_data['新增死亡数'] / total_data['新增死亡数'].mean()
total_data['新增爆头数'] = total_data['新增爆头数'] / total_data['新增爆头数'].mean()
total_data['新增伤害量'] = total_data['新增伤害量'] / total_data['新增伤害量'].mean()
total_data['新增MVP次数'] = total_data['新增MVP次数'] / total_data['新增MVP次数'].mean()
total_data['K/D'] = total_data['K/D'] / total_data['K/D'].mean()
total_data['HS'] = total_data['HS'] / total_data['HS'].mean()


# 周得分
original_data['Activate'] = (total_data['新增击杀数'] + total_data['新增死亡数']).round(2)
original_data['Score'] = (total_data['新增击杀数'] * 0.25 - total_data['新增死亡数'] * 0.1 + total_data['新增伤害量'] * 0.2 + total_data['HS'] * 0.2 + total_data['新增MVP次数'] * 0.15 + total_data['K/D'] * 0.2).round(2)

# 按 Score 列降序排序
original_data = original_data.sort_values(by='Score', ascending=False)




# 打印指定的列
#print(original_data[['Nickname', 'Score', 'Activate']])

output_csv_path = f'CS/data/week/weekly_stats_{year}-{week}.csv'
original_data.to_csv(output_csv_path, index=False, encoding='utf-8')
print(f"{year}-{week}数据已保存到 {output_csv_path}")



# 将 DataFrame 写入 MySQL
original_data = original_data.fillna(0)  # 将 NaN 替换为 0
for _, row in original_data.iterrows():
    cursor.execute(
        """
        INSERT INTO weekly (
            Nickname, 新增击杀数, 新增死亡数, 新增爆头数, 新增伤害量, 新增MVP次数, KD, HS, Score, Activate, year, week
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            row["Nickname"],
            row["新增击杀数"],
            row["新增死亡数"],
            row["新增爆头数"],
            row["新增伤害量"],
            row["新增MVP次数"],
            row["K/D"],
            row["HS"],
            row["Score"],
            row["Activate"],
            year,
            week
        )
    )
# 提交更改并关闭连接
conn.commit()
cursor.close()  # 关闭游标
conn.close()
print("数据已保存到 数据库")
