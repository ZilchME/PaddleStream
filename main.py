"""
StreamASR Web Server
实时语音识别Web服务

使用方法:
1. 启动ASR服务器 (PaddleSpeech)
2. 运行此脚本: python main.py
3. 在浏览器中打开: http://localhost:5000
4. 点击"开始录音"进行语音识别

也可以直接使用原始麦克风模式:
python -c "from paddlespeech_client import ASROnlineClientExecutor; print(ASROnlineClientExecutor()('mic', '127.0.0.1', 8090))"
"""

import sys
import os

def run_web_server():
    """启动Web服务器"""
    try:
        import uvicorn
        from web_server import socket_app
        print("=" * 50)
        print("🎤 StreamASR Web服务器启动中...")
        print("=" * 50)
        print("请确保PaddleSpeech ASR服务器已启动:")
        print("默认地址: ws://127.0.0.1:8090/paddlespeech/asr/streaming")
        print("")
        print("Web界面地址: http://localhost:8000")
        print("=" * 50)
        
        uvicorn.run(socket_app, host='0.0.0.0', port=8000)
    except ImportError as e:
        print("错误: 缺少依赖包，请安装:")
        print("pip install fastapi uvicorn[standard] python-socketio aiohttp")
        print(f"详细错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"启动Web服务器失败: {e}")
        sys.exit(1)

def run_mic_mode():
    """运行原始麦克风模式"""
    from paddlespeech_client import ASROnlineClientExecutor
    
    print("=" * 50)
    print("🎤 StreamASR 麦克风模式")
    print("=" * 50)
    
    asrclient_executor = ASROnlineClientExecutor()
    res = asrclient_executor(
        input="mic",
        server_ip="127.0.0.1",
        port=8090,
        # punc_server_ip="127.0.0.1",
        # punc_server_port=8190,
    )
    print(f"识别结果: {res}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--mic":
        # 麦克风模式
        run_mic_mode()
    else:
        # Web服务器模式 (默认)
        run_web_server()
