# StreamASR Web版本

这是一个实时语音识别的Web应用，将原本的麦克风直接输入改造为Web前端输入。

## 功能特性

- 🎤 支持Web浏览器麦克风录音
- 🌐 WebSocket实时通信
- 📝 实时语音转文字
- 🔗 支持PaddleSpeech ASR服务器
- 📱 响应式Web界面

## 架构说明

### 原始架构
```
麦克风 → PyAudio → ASR处理 → PaddleSpeech服务器 → 文字结果
```

### 新架构
```
Web浏览器麦克风 → WebSocket → Flask服务器 → ASR处理 → PaddleSpeech服务器 → 文字结果 → WebSocket → Web界面
```

## 文件说明

- `audio_hander.py` - 音频处理模块，新增`WebAudioHandler`类
- `web_server.py` - Flask-SocketIO Web服务器
- `templates/index.html` - Web前端界面
- `main.py` - 主程序，支持Web模式和麦克风模式
- `paddlespeech_client.py` - ASR客户端，支持Web音频输入
- `requirements.txt` - 依赖包列表

## 安装和使用

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 启动PaddleSpeech ASR服务器
确保PaddleSpeech ASR服务器运行在 `ws://127.0.0.1:8090/paddlespeech/asr/streaming`

### 3. 启动Web服务器
```bash
# Web模式 (默认)
python main.py

# 或者原始麦克风模式
python main.py --mic
```

### 4. 访问Web界面
打开浏览器访问: `http://localhost:5000`

## API接口

### WebSocket事件

#### 客户端发送:
- `start_asr` - 开始ASR处理
  ```json
  {
    "server_ip": "127.0.0.1",
    "server_port": 8090
  }
  ```

- `audio_data` - 发送音频数据
  ```json
  {
    "audio": [音频数据数组]
  }
  ```

- `stop_asr` - 停止ASR处理

#### 服务器发送:
- `connected` - 连接成功
- `asr_started` - ASR处理开始
- `asr_result` - 识别结果
- `asr_error` - 处理错误
- `error` - 一般错误

## 技术细节

### 音频处理
- 采样率: 16kHz
- 声道: 单声道
- 格式: 16位PCM
- 缓冲区: 1024样本

### Web音频处理流程
1. 浏览器获取麦克风权限
2. AudioContext处理音频流
3. ScriptProcessor节点处理音频块
4. 转换为16位整数数组
5. 通过WebSocket发送到服务器
6. 服务器缓冲并转发给ASR服务

### 会话管理
- 每个WebSocket连接对应一个ASR会话
- 支持多个并发会话
- 自动清理断开的会话

## 注意事项

1. 浏览器需要HTTPS或localhost才能访问麦克风
2. 确保PaddleSpeech服务器先启动
3. 音频处理需要一定的计算资源
4. WebSocket连接断开会自动清理资源

## 故障排除

### 常见问题
1. **无法访问麦克风**: 检查浏览器权限设置
2. **连接ASR服务器失败**: 确认服务器地址和端口
3. **音频质量差**: 调整麦克风设置或网络环境
4. **依赖包错误**: 使用pip安装requirements.txt中的包

### 日志查看
服务器端会输出详细日志，包括:
- WebSocket连接状态
- 音频数据接收情况
- ASR处理进度
- 错误信息

## 扩展功能

可以考虑添加的功能:
- 音频录制和回放
- 多语言支持
- 用户认证
- 历史记录
- 音频质量监控
- 批处理音频文件
