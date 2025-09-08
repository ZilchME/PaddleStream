# StreamASR Web版本

这是一个实时语音识别和语音合成的Web应用，支持语音转文字（ASR）和文字转语音（TTS）功能。

## 功能特性

- 🎤 支持Web浏览器麦克风录音
- 🔊 实时语音合成（TTS）
- 📝 流式文本语音合成
- 🌐 WebSocket实时通信
- 📝 实时语音转文字（ASR）
- 🔗 支持PaddleSpeech ASR/TTS服务器
- 📱 响应式Web界面
- 🔄 支持流式文本输入和实时合成

## 架构说明

### ASR架构
```
Web浏览器麦克风 → WebSocket → Flask服务器 → ASR处理 → PaddleSpeech服务器 → 文字结果 → WebSocket → Web界面
```

### TTS架构
```
Web界面文本输入 → WebSocket → Flask服务器 → TTS处理 → PaddleSpeech服务器 → 音频数据 → WebSocket → Web界面播放
```

### 流式TTS架构
```
Web界面流式文本 → WebSocket → 文本缓冲区 → 智能分句 → TTS处理 → PaddleSpeech服务器 → 流式音频 → Web界面实时播放
```

## 文件说明

- `audio_hander.py` - 音频处理模块，支持ASR和TTS
- `web_server.py` - Flask-SocketIO Web服务器，包含TTSBufferSession类
- `templates/index.html` - 主页面
- `templates/tts_test.html` - 基础TTS测试页面
- `templates/stream_tts_test.html` - 流式TTS测试页面
- `paddlespeech_client.py` - ASR/TTS客户端
- `config.py` - 配置文件
- `requirements.txt` - 依赖包列表
- `README_STREAM_TTS.md` - 流式TTS详细文档
- `README_SOCKETIO_EVENTS.md` - Socket.IO事件接口文档

## 安装和使用

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 启动PaddleSpeech服务器
```bash
# ASR服务器
paddlespeech_server start --config_file asr_config.yaml

# TTS服务器  
paddlespeech_server start --config_file tts_config.yaml
```

### 3. 启动Web服务器
```bash
python web_server.py
```

### 4. 访问Web界面
- 主页面: `http://localhost:8000`
- 基础TTS测试: `http://localhost:8000/tts`
- 流式TTS测试: `http://localhost:8000/stream-tts`

## API接口

### ASR相关事件

#### 客户端发送:
- `start_asr` - 开始ASR处理
- `audio_data` - 发送音频数据
- `stop_asr` - 停止ASR处理

#### 服务器发送:
- `asr_started` - ASR处理开始
- `asr_partial_result` - 部分识别结果
- `asr_result` - 最终识别结果
- `asr_stopped` - ASR处理停止
- `asr_error` - ASR错误

### TTS相关事件

#### 基础TTS
- `start_tts` - 开始TTS合成
- `tts_stream` - 音频流数据
- `tts_completed` - 合成完成
- `stop_tts` - 停止TTS
- `tts_error` - TTS错误

#### 流式TTS
- `start_stream_tts` - 启动流式TTS会话
- `stream_text` - 发送文本片段
- `flush_tts_buffer` - 清空缓冲区
- `get_tts_status` - 获取TTS状态
- `tts_buffer_status` - 缓冲区状态更新
- `tts_buffer_flushed` - 缓冲区已清空

详细的事件格式请参考 `README_SOCKETIO_EVENTS.md`

## 流式TTS特性

### 智能分句
- 支持中文和英文标点符号分句
- 主要分句符：句号、问号、感叹号、换行符
- 次要分句符：逗号、分号（缓冲区过大时使用）
- 缓冲区大小限制，防止内存溢出

### 实时合成
- 后台异步处理，不阻塞文本输入
- 按句子顺序合成，保证输出连贯性
- 支持流式音频输出
- 合成状态实时反馈

### 使用场景
- 实时聊天语音合成
- 流式翻译语音输出
- 智能客服对话
- 实时新闻播报
- 在线教育语音合成

## 技术细节

### 音频处理
- 采样率: 16kHz (ASR) / 24kHz (TTS)
- 声道: 单声道
- 格式: 16位PCM
- 缓冲区: 1024样本

### 流式TTS处理流程
1. 客户端发送文本片段
2. 服务器累积到文本缓冲区
3. 使用正则表达式智能分句
4. 提取完整句子加入合成队列
5. 后台线程异步合成音频
6. 流式返回音频数据到客户端
7. 客户端实时播放音频

### 会话管理
- 每个WebSocket连接对应独立的ASR/TTS会话
- 支持多个并发会话
- 自动清理断开的会话资源
- 流式TTS支持独立的缓冲区管理

## 配置说明

在 `config.py` 中可以配置:

```python
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

# Socket.IO配置
SOCKETIO_CONFIG = {"cors_allowed_origins": "*", "async_mode": "asgi"}
SOCKETIO_PATH = "/socket.io/"
```

## 注意事项

1. **浏览器权限**: 需要HTTPS或localhost才能访问麦克风
2. **服务器启动**: 确保PaddleSpeech ASR/TTS服务器先启动
3. **资源消耗**: 音频处理和语音合成需要一定的计算资源
4. **网络连接**: WebSocket连接断开会自动清理资源
5. **流式TTS**: 文本发送完毕后记得调用`flush_tts_buffer`清空缓冲区

## 故障排除

### 常见问题
1. **无法访问麦克风**: 检查浏览器权限设置
2. **连接ASR/TTS服务器失败**: 确认服务器地址和端口
3. **音频质量差**: 调整麦克风设置或网络环境
4. **TTS无声音**: 检查音频播放设备和音量设置
5. **流式TTS不工作**: 确认已启动流式TTS会话
6. **依赖包错误**: 使用pip安装requirements.txt中的包

### 日志查看
服务器端会输出详细日志，包括:
- WebSocket连接状态
- 音频数据接收情况
- ASR/TTS处理进度
- 流式TTS缓冲区状态
- 错误信息

## 扩展功能

可以考虑添加的功能:
- 音频录制和回放
- 多语言支持
- 用户认证和会话持久化
- 历史记录存储
- 音频质量监控
- 批处理音频文件
- 情感语音合成
- 语音速度和音调调节
- 多说话人TTS
- 自定义分句规则
