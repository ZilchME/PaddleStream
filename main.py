import sys
import uvicorn
from web_server import socket_app

if __name__ == "__main__":
    try:
        print("请确保PaddleSpeech ASR服务器已启动:")
        print("=" * 50)

        uvicorn.run(socket_app, host="0.0.0.0", port=8008)
    except ImportError as e:
        print("错误: 缺少依赖包，请安装:")
        print(f"详细错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"启动Web服务器失败: {e}")
        sys.exit(1)
