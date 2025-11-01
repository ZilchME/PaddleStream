# StreamASR 配置文件

# Web服务器配置
WEB_SERVER_CONFIG = {"host": "0.0.0.0", "port": 8000}

# ASR服务器配置
ASR_SERVER_CONFIG = {
    "default_ip": "127.0.0.1",
    "default_port": 8090,
    "endpoint": "/paddlespeech/asr/streaming",
}

# TTS服务器配置
TTS_SERVER_CONFIG = {
    "default_ip": "127.0.0.1",
    "default_port": 8090,
    "endpoint": "/paddlespeech/tts/streaming",
}

# Socket.IO 配置
SOCKETIO_CONFIG = {"cors_allowed_origins": "*", "async_mode": "asgi"}

# Socket.IO 路径配置
SOCKETIO_PATH = "/socket.io/"

# LLM API 配置
LLM_API_CONFIG = {
    "url": "http://10.229.33.207:48080/stream",  # 请根据实际情况修改
    "timeout": 120,
}
