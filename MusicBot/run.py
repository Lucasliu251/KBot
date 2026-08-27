#!/usr/bin/env python3
import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

DEBUG_LOG_PATH = Path(__file__).resolve().with_name('debug.log')

# 配置基础日志
logging.basicConfig(
    level=logging.INFO,  # 保持INFO级别，显示正常信息
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(DEBUG_LOG_PATH, encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)

# 只关闭Flask的HTTP访问日志，保留其他日志
logging.getLogger('werkzeug').setLevel(logging.ERROR)

try:
    # 加载环境变量
    logger.info("正在加载环境变量...")
    # 始终读取 MusicBot 自己的 .env，并覆盖父进程残留的旧机器人配置。
    load_dotenv(dotenv_path=Path(__file__).with_name('.env'), override=True)

    logger.info("正在启动本地网易云 API...")
    from local_netease_service import local_netease_service
    local_netease_service.start()

    logger.info("正在初始化应用...")
    from app import create_app
    app = create_app()

    if __name__ == '__main__':
        host = os.getenv('HOST', '0.0.0.0')
        port = int(os.getenv('PORT', 8004))
        debug = os.getenv('DEBUG', 'True').lower() in ('true', '1', 't')
        
        logger.info(f"启动服务器: http://{host}:{port} [DEBUG: {debug}]")
        app.run(host=host, port=port, debug=debug, use_reloader=False)
        
except Exception as e:
    logger.critical(f"启动失败: {str(e)}", exc_info=True)
    sys.exit(1)
