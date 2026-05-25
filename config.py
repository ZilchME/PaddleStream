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

# PUNC服务器配置
# 可选，如果不使用标点服务，可以将 default_ip 和 default_port 设置为 None
# 或者不设置该选项
PUNC_SERVER_CONFIG = {
    "default_ip": "127.0.0.1",
    "default_port": 8190,
}

# Socket.IO 配置
SOCKETIO_CONFIG = {"cors_allowed_origins": "*", "async_mode": "asgi"}

# Socket.IO 路径配置
SOCKETIO_PATH = "/socket.io/"

# LLM API 配置
LLM_API_CONFIG = {
    "url": "http://127.0.0.1:48080/stream",  # 请根据实际情况修改
    "timeout": 120,
}
