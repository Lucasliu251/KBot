from flask import Flask, send_from_directory
from pathlib import Path

app = Flask(__name__)
WEB_DIR = Path(__file__).resolve().parent

# 配置路由，提供HTML文件
@app.route('/')
def serve_html():
    return send_from_directory(WEB_DIR, 'ECharts.html')  # 访问根路径时，返回你的HTML文件

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)  # 在服务器的0.0.0.0地址上运行，监听5000端口
