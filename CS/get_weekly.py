import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import configparser
import subprocess
import sys
from pathlib import Path
from sqlalchemy import create_engine, text

CS_DIR = Path(__file__).resolve().parent
DATA_DIR = CS_DIR / 'data'
WEEK_DIR = DATA_DIR / 'week'


def load_db_uri():
    """读取 CS/config.ini 中的 PostgreSQL 连接串。

    @returns: SQLAlchemy DB_URI
    @changelog
    - 2026-08-22: 周报写入从远程 MySQL 改为本机 PostgreSQL (Author: KBot)
    """
    config = configparser.ConfigParser()
    with (CS_DIR / 'config.ini').open('r', encoding='utf-8') as f:
        config.read_file(f)
    return config['SQL']['DB_URI']


subprocess.run([sys.executable, CS_DIR / 'get_data.py'], check=True)
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

# 连接本机 PostgreSQL trashbox；中文列名与 Nickname 需保持引号
engine = create_engine(load_db_uri())

# 初始化一个空的 DataFrame 用于累加数据
total_data = pd.DataFrame()

# 遍历7天的文件
for date in date_list:
    file_path = DATA_DIR / f'player_stats_{date}.txt'


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

WEEK_DIR.mkdir(parents=True, exist_ok=True)
output_csv_path = WEEK_DIR / f'weekly_stats_{year}-{week}.csv'
original_data.to_csv(output_csv_path, index=False, encoding='utf-8')
print(f"{year}-{week}数据已保存到 {output_csv_path}")



# 将 DataFrame 写入 PostgreSQL weekly（列名与迁库时的 MySQL 原名一致）
original_data = original_data.fillna(0)  # 将 NaN 替换为 0
insert_weekly = text(
    """
    INSERT INTO weekly (
        "Nickname", "新增击杀数", "新增死亡数", "新增爆头数", "新增伤害量",
        "新增MVP次数", "KD", "HS", "Score", "Activate", year, week
    ) VALUES (
        :nickname, :kills, :deaths, :headshots, :damage,
        :mvp, :kd, :hs, :score, :activate, :year, :week
    )
    """
)
with engine.begin() as conn:
    for _, row in original_data.iterrows():
        conn.execute(
            insert_weekly,
            {
                "nickname": row["Nickname"],
                "kills": row["新增击杀数"],
                "deaths": row["新增死亡数"],
                "headshots": row["新增爆头数"],
                "damage": row["新增伤害量"],
                "mvp": row["新增MVP次数"],
                "kd": row["K/D"],
                "hs": row["HS"],
                "score": row["Score"],
                "activate": row["Activate"],
                "year": year,
                "week": week,
            },
        )
print("数据已保存到 数据库")
