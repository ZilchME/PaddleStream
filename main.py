import sys

import uvicorn

from config import WEB_SERVER_CONFIG
from web_server import socket_app


if __name__ == "__main__":
    try:
        print("请确保 PaddleSpeech 相关服务器已启动:")
        print("=" * 50)
        uvicorn.run(
            socket_app,
            host=WEB_SERVER_CONFIG["host"],
            port=WEB_SERVER_CONFIG["port"],
        )
    except ImportError as e:
        print("错误: 缺少依赖包")
        print(f"详细错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"启动Web服务器失败: {e}")
        sys.exit(1)
