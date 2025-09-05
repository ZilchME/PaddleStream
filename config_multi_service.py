# StreamASR 配置文件 - 多服务版本示例

# Web服务器配置
WEB_SERVER_CONFIG = {
    "host": "0.0.0.0",
    "port": 8000,
    "reload": True
}

# ASR服务器配置
ASR_SERVER_CONFIG = {
    "default_ip": "127.0.0.1",
    "default_port": 8090,
    "endpoint": "/paddlespeech/asr/streaming"
}

# Socket.IO 配置
SOCKETIO_CONFIG = {
    "cors_allowed_origins": "*",
    "async_mode": "asgi"
}

# 当前使用的Socket.IO路径配置
# 你可以修改这个路径来自定义Socket.IO的endpoint
SOCKETIO_PATH = "/socket.io/"

# 多服务Socket.IO路径配置示例
SOCKETIO_PATHS = {
    "asr": "/asr/socket.io/",           # ASR服务
    "tts": "/tts/socket.io/",           # TTS服务  
    "nlp": "/nlp/socket.io/",           # NLP服务
    "default": "/socket.io/"            # 默认服务
}

# 服务路由配置
SERVICE_ROUTES = {
    "asr": {
        "path": "/asr",
        "socketio_path": SOCKETIO_PATHS["asr"],
        "description": "语音识别服务"
    },
    "tts": {
        "path": "/tts", 
        "socketio_path": SOCKETIO_PATHS["tts"],
        "description": "语音合成服务"
    },
    "nlp": {
        "path": "/nlp",
        "socketio_path": SOCKETIO_PATHS["nlp"], 
        "description": "自然语言处理服务"
    }
}

# 当前激活的服务（从SOCKETIO_PATHS中选择）
CURRENT_SERVICE = "default"  # 可以改为 "asr", "tts", "nlp" 等

# 根据当前服务设置Socket.IO路径
if CURRENT_SERVICE in SOCKETIO_PATHS:
    SOCKETIO_PATH = SOCKETIO_PATHS[CURRENT_SERVICE]
