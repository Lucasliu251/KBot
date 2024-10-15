from flask import Flask, request, jsonify
import time
from threading import Timer
app = Flask(__name__)

# 全局变量存储接收到的游戏数据
game_data = {
    "比赛信息": {},
    "队伍信息": {}
}

def clean_old_data():
    global game_data
    game_data = {       # 重置 game_data
        "比赛信息": {},
        "队伍信息": {}
    }  
    print('data更新')
    Timer(30, clean_old_data).start()
    

@app.route('/gsi', methods=['POST'])
def handle_gsi():
    global game_data 
    data = request.get_json()
    #game_data = data.get("map",{})

    # 提取比赛信息
    match_info = {
        "比赛模式": data.get("map", {}).get("mode", "未知"),
        "比赛地图": data.get("map", {}).get("name", "未知"),
        "总比分": f"{data.get('map', {}).get('team_ct', {}).get('score', 0)}:{data.get('map', {}).get('team_t', {}).get('score', 0)}",
        "比赛状态": data.get("map", {}).get("phase", "未开始"),
        "炸弹状态": data.get("round", {}).get("bomb", "未安放"),
        "当前回合阶段": data.get("round", {}).get("phase", "未知"),
        "当前回合胜利方": data.get("round", {}).get("win_team", "未知"),
        "回合结算": data.get('map', {}).get('round_wins', {})
    }

    # 每次接收到新的比赛信息时，更新比赛信息
    game_data["比赛信息"] = match_info

    # 获取玩家信息
    player_data = data.get("player", {})

    if player_data:
        steamid = player_data.get("steamid", "未知")
        player_info = {
            "玩家状态": {
                "生命值": player_data.get("state", {}).get("health", "0"),
                "护甲": player_data.get("state", {}).get("armor", "0"),
                "武器装备价值": player_data.get("state", {}).get("equipment_value", "0"),
                "是否有头盔": player_data.get("state", {}).get("helmet", "false"),
                "当前闪光状态": player_data.get("state", {}).get("flashed", "0")
            },
            "玩家武器": [
                {
                    "武器名称": weapon.get("name", "未知"),
                    "武器状态": weapon.get("state", "未知")
                } for weapon in player_data.get("weapons", {}).values()
            ],
            "玩家比赛统计": {
                "击杀数": player_data.get("match_stats", {}).get("kills", "0"),
                "助攻数": player_data.get("match_stats", {}).get("assists", "0"),
                "死亡数": player_data.get("match_stats", {}).get("deaths", "0"),
                "MVP次数": player_data.get("match_stats", {}).get("mvps", "0"),
                "总分数": player_data.get("match_stats", {}).get("score", "0")
            },
            "阵营": player_data.get("team", "未知"),  # 获取玩家阵营
            #"provider": data.get("provider",{})
        }

        # 将玩家信息存储在 game_data 的 "队伍信息" 中，按 steamid 进行区分
        game_data["队伍信息"][steamid] = player_info

    return jsonify({"message": "POST数据已成功接收"}), 200

# 添加GET方法以便查看存储的数据
@app.route('/gsi', methods=['GET'])
def get_gsi_data():
    if game_data:
        return jsonify(game_data)
    else:
        return jsonify({"message": "尚未接收到任何数据"}), 200


# 初始启动定时清理任务
Timer(20, clean_old_data).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
