# StreamASR 配置文件

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

# Socket.IO 路径配置
# 你可以修改这个路径来自定义Socket.IO的endpoint
# 默认 Socket.IO 使用 /socket.io/ 路径
# SOCKETIO_PATH = "/socket.io/"

# 示例：为ASR服务创建专用路径
SOCKETIO_PATH = "/asr/socket.io/"

# 示例：为不同服务创建不同路径
# SOCKETIO_PATH = "/services/asr/socket.io/"
