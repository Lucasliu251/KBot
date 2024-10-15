from flask import Flask, send_from_directory

app = Flask(__name__)

# 配置路由，提供HTML文件
@app.route('/')
def serve_html():
    return send_from_directory('C:/Users/Administrator/Desktop/KooK_Bot/CS/Web/frontend', 'ECharts.html')  # 访问根路径时，返回你的HTML文件

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)  # 在服务器的0.0.0.0地址上运行，监听5000端口
