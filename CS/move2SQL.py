import os
import re
import pandas as pd
from sqlalchemy import create_engine
from pathlib import Path

# ================= 配置区域 =================
DATA_DIR = Path(__file__).resolve().parent / "data"
# 本机 PostgreSQL trashbox（程序账户）；历史 TXT 一次性导入用
DB_URI = "postgresql+psycopg2://trashbox:88888888@127.0.0.1:5432/trashbox"

NICKNAME_TO_STEAMID = {
    # ... (保持你之前的完整映射表不变)
    "Lucas": "76561199047005402",
    "哞哞": "76561198322540863",
    "lilt": "76561198812098457",
    "Ari": "76561198819631157",
    "法兰西多士": "76561198908180415",
    "和明天相逢": "76561199501933725",
    "隗遗生": "76561198404665308",
    "小牛马": "76561199269293274",
    "bob": "76561198397613059",
    "波奇": "76561198983823751",
    "餐具大师": "76561198859185989",
    "Ash": "76561199195489362",
    "这很机车": "76561199379568178",
    "京极真": "76561199698064063",
    "你这只臭猫": "76561198981475055",
    "彦祖没有我潇": "76561199040451294",
    "我没文化": "76561199748267569",
    "阿司匹林": "76561198421884036",
    "小熊饼干": "76561198850980110",
    "深藏Blue": "76561198809705149",
    "大泡泡": "76561199081813494",
    "axxibar": "76561198808763376",
    "GhostFace": "76561199480522550",
    "林北": "76561199131985420",
    "摇滚青年": "76561198045794606",
    "yonnesy": "76561198961350402",
    "张部长": "76561198118013131",
    "小聪铭": "76561199192766204",
    "校草阿源": "76561199100801517",
    "MountainH": "76561198096805173"
}

def extract_date_from_filename(filename):
    match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    if match: return match.group(1)
    return None

def parse_adaptive(file_path, record_date):
    """
    自适应解析器：尝试多种模式来匹配不同时期的文件格式
    """
    cleaned_data = []
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 合并为单行以便正则处理
    content = re.sub(r'\s+', ' ', content)
    
    # === 定义多种匹配模式 (优先级从高到低：越完整的越先匹配) ===
    
    # 模式 A (最完整): 包含 伤害量 和 MVP (如 12-26 及以后, 12-25)
    # 特征：昵称 + 4个基础数字(K/D/incK/incD) + 击杀比 + 爆头数/增/率 + 伤害/增 + MVP/增
    pattern_full = re.compile(
        r"Top\d+\s+(\S+)\s+"      # Nickname
        r"(\d+)\s+"               # total_kills
        r"(\d+)\s+"               # total_deaths
        r"\d+\s+\d+\s+[\d\.]+\s+" # 忽略 incK, incD, Ratio
        r"(\d+)\s+"               # total_headshots
        r"\d+\s+[\d%]+\s+"        # 忽略 incHS, Rate
        r"(\d+)\s+"               # total_damage
        r"\d+\s+"                 # 忽略 incDmg
        r"(\d+)"                  # total_mvps
    )
    
    # 模式 B (中等): 包含 爆头数，但无伤害/MVP (如 12-23, 12-24)
    # 特征：昵称 + 4个基础数字 + 击杀比 + 爆头数 + 增 + 率 (后面没有伤害了)
    pattern_medium = re.compile(
        r"Top\d+\s+(\S+)\s+"      # Nickname
        r"(\d+)\s+"               # total_kills
        r"(\d+)\s+"               # total_deaths
        r"\d+\s+\d+\s+[\d\.]+\s+" # 忽略 incK, incD, Ratio
        r"(\d+)\s+"               # total_headshots
        r"\d+\s+[\d%]+"           # 忽略 incHS, Rate
        # 后面不再匹配伤害和MVP
    )
    
    # 模式 C (最简): 只有 击杀/死亡 (如 12-22)
    # 特征：昵称 + 4个基础数字 + 击杀比 (后面啥都没了)
    pattern_basic = re.compile(
        r"Top\d+\s+(\S+)\s+"      # Nickname
        r"(\d+)\s+"               # total_kills
        r"\d+\s+\d+\s+[\d\.]+"    # 忽略 incK, incD, Ratio
    )
    
    # === 策略：对每个 TopX 块进行独立尝试 ===
    # 我们不能简单用 findall，因为不同文件的 pattern 不同。
    # 更好的方法是：把 content 切分成一个个 "TopX ..." 的块，然后对每个块试 pattern。
    
    # 1. 切分块 (利用 "Top" 关键字)
    # result: ['', '1 Nickname...', '2 Nickname...']
    chunks = re.split(r'(?=Top\d+)', content)
    
    for chunk in chunks:
        if not chunk.strip(): continue
        
        nickname = None
        stats = {}
        
        # 依次尝试匹配
        
        # 尝试 A
        m = pattern_full.search(chunk)
        if m:
            nickname = m.group(1)
            stats = {
                "total_kills": int(m.group(2)),
                "total_deaths": int(m.group(3)),
                "total_HS": int(m.group(4)),
                "total_damage": int(m.group(5)),
                "total_mvps": int(m.group(6))
            }
        
        # 尝试 B (如果 A 没匹配上)
        elif pattern_medium.search(chunk):
            m = pattern_medium.search(chunk)
            nickname = m.group(1)
            stats = {
                "total_kills": int(m.group(2)),
                "total_deaths": int(m.group(3)),
                "total_HS": int(m.group(4)),
                "total_damage": 0, # 缺失补0
                "total_mvps": 0    # 缺失补0
            }
            
        # 尝试 C (如果 B 也没匹配上)
        elif pattern_basic.search(chunk):
            m = pattern_basic.search(chunk)
            nickname = m.group(1)
            stats = {
                "total_kills": int(m.group(2)),
                "total_deaths": 0,
                "total_HS": 0, # 缺失补0
                "total_damage": 0,
                "total_mvps": 0
            }
            
        if nickname:
            steam_id = NICKNAME_TO_STEAMID.get(nickname)
            if steam_id:
                record = {
                    "record_date": record_date,
                    "steam_id": steam_id,
                    "nickname": nickname,
                    **stats,
                    # 其他默认0
                    "total_rounds_played": 0, "total_wins": 0, 
                    "total_time_played": 0, "total_money_earned": 0
                }
                cleaned_data.append(record)
            else:
                pass # print(f"未知用户: {nickname}")
                
    return cleaned_data

def migrate():
    engine = create_engine(DB_URI)
    files = [f for f in os.listdir(DATA_DIR) if f.endswith(".txt")]
    files.sort()
    
    print(f"📂 开始处理 {len(files)} 个文件 (自适应模式)...\n")

    for filename in files:
        record_date = extract_date_from_filename(filename)
        if not record_date: continue
        
        file_path = os.path.join(DATA_DIR, filename)
        # 简单打印一下，不换行
        print(f"🔄 {record_date} ...", end="")
        
        try:
            data = parse_adaptive(file_path, record_date)
            if not data:
                print(" [跳过] (无匹配数据)")
                continue
                
            df = pd.DataFrame(data)
            df.to_sql('daily', engine, if_exists='append', index=False, chunksize=1000)
            print(f" ✅ {len(df)} 条")
            
        except Exception as e:
            if "Duplicate entry" in str(e) or "unique" in str(e).lower():
                print(" ⚠️ [重复]")
            else:
                print(f" ❌ {e}")

    print("\n🎉 完成！")

if __name__ == "__main__":
    migrate()
