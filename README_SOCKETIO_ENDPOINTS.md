# StreamASR Socket.IO Endpoint 自定义指南

## 概述

本项目支持自定义Socket.IO的endpoint路径，便于管理多个服务接口。

## 配置Socket.IO Endpoint

### 1. 基础配置

在 `config.py` 中修改 `SOCKETIO_PATH` 变量：

```python
# 默认路径
SOCKETIO_PATH = "/socket.io/"

# 自定义ASR服务路径
SOCKETIO_PATH = "/asr/socket.io/"

# 自定义其他服务路径
SOCKETIO_PATH = "/services/asr/socket.io/"
```

### 2. 多服务配置

使用 `config_multi_service.py` 配置多个服务：

```python
SOCKETIO_PATHS = {
    "asr": "/asr/socket.io/",           # ASR服务
    "tts": "/tts/socket.io/",           # TTS服务  
    "nlp": "/nlp/socket.io/",           # NLP服务
    "default": "/socket.io/"            # 默认服务
}

# 选择当前激活的服务
CURRENT_SERVICE = "asr"  # 或 "tts", "nlp", "default"
```

## 客户端连接

### JavaScript客户端

```javascript
// 连接到自定义endpoint
const socket = io('http://localhost:8000', {
    path: '/asr/socket.io/',  // 自定义路径
    transports: ['websocket', 'polling']
});
```

### Python客户端

```python
import socketio

# 连接到自定义endpoint
sio = socketio.Client()
sio.connect('http://localhost:8000', socketio_path='/asr/socket.io/')
```

## 服务器配置示例

### 单服务模式 (web_server.py)

```python
# 使用配置文件中的自定义路径
socket_app = socketio.ASGIApp(sio, app, socketio_path=SOCKETIO_PATH)
```

### 多服务模式 (web_server_multi_service.py)

支持同时运行多个服务，每个服务有独立的Socket.IO endpoint：

- ASR服务: `/asr/socket.io/`
- TTS服务: `/tts/socket.io/`
- NLP服务: `/nlp/socket.io/`

## API端点

### 健康检查
```
GET /health
```
返回当前Socket.IO配置信息

### 服务列表
```
GET /services
```
返回所有可用服务及其endpoint信息

## 使用方法

### 1. 启动默认ASR服务
```bash
python web_server.py
```

### 2. 启动多服务模式
```bash
python web_server_multi_service.py
```

### 3. 访问Web界面
打开浏览器访问: `http://localhost:8000`

## 自定义路径的优势

1. **服务隔离**: 不同服务使用不同的endpoint，避免冲突
2. **路由管理**: 便于负载均衡和反向代理配置
3. **版本控制**: 可以为不同版本的API使用不同路径
4. **安全性**: 可以对不同服务设置不同的访问控制

## 示例配置

### Nginx反向代理配置
```nginx
location /asr/socket.io/ {
    proxy_pass http://localhost:8000/asr/socket.io/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}

location /tts/socket.io/ {
    proxy_pass http://localhost:8001/tts/socket.io/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```

### Docker Compose配置
```yaml
version: '3.8'
services:
  asr-service:
    build: .
    ports:
      - "8000:8000"
    environment:
      - SOCKETIO_PATH=/asr/socket.io/
      
  tts-service:
    build: .
    ports:
      - "8001:8000"
    environment:
      - SOCKETIO_PATH=/tts/socket.io/
```

## 注意事项

1. 确保客户端和服务器的Socket.IO路径配置一致
2. 修改路径后需要重启服务器
3. 在负载均衡环境中，确保WebSocket连接的粘性会话
4. 自定义路径必须以 `/` 开头和结尾
