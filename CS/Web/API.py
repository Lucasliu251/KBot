from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import json

app = Flask(__name__)
CORS(app)  # 启用CORS，允许所有来源访问

# 定义API路由
@app.route('/api/data', methods=['GET'])
def get_data():
    json_path = 'C:/Users/Administrator/Desktop/KooK_Bot/CS/data/dirt.json'
    with open(json_path, 'r', encoding='utf-8') as json_file:
        data = json.load(json_file)
    return jsonify(data)

@app.route('/web')
def serve_html():
    return send_from_directory('C:/Users/Administrator/Desktop/KooK_Bot/CS/Web', 'ECharts.html')  # 访问根路径时，返回你的HTML文件

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)  # 启动服务器，监听5000端口
