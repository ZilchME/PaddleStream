# 流式ASR、TTS服务端

### 简介

对百度飞桨 [PaddleSpeech](https://github.com/PaddlePaddle/PaddleSpeech/) 服务进行二次封装，支持流式实时语音识别，支持文本逐字输入的流式语音合成。

### 主要功能

1. **流式语音识别 (ASR)**: 实时处理音频流并返回识别结果
2. **流式语音合成 (TTS)**: 支持文本逐字输入的流式语音合成
3. **LLM 流式对话**: 后端处理 LLM SSE 流式响应,通过 WebSocket 实时转发
4. **WebSocket 通信**: 基于 Socket.IO 的实时双向通信

### 前置服务

PaddleSpeech 支持通过服务配置文件作为服务端程序直接启动，本项目基于该服务端运行

```shell
paddlespeech_server start --config_file application.yaml
```

配置文件可以参考根目录的 `application.yaml`

可选开启ASR结果的标点补全服务，配置文件参考官方库提供的 demo 即可

```shell
paddlespeech_server start --config_file conf/punc_application.yaml
```

### 安装依赖

```bash
pip install -r requirements.txt
```

主要依赖:
- fastapi: Web 框架
- uvicorn: ASGI 服务器
- python-socketio: WebSocket 支持

### 配置说明

编辑 `config.py` 文件进行配置:

```python
# LLM API 配置 (新增)
LLM_API_CONFIG = {
    "url": "http://your-llm-api-url/api/stream",  # 修改为你的LLM API地址
}

# ASR服务器配置
ASR_SERVER_CONFIG = {
    "default_ip": "127.0.0.1",
    "default_port": 8090,
}

# TTS服务器配置
TTS_SERVER_CONFIG = {
    "default_ip": "127.0.0.1",
    "default_port": 8090,
}
```

### 启动服务

```bash
python main.py
```

服务将在 `http://0.0.0.0:8008` 启动。

### 事件接口

#### ASR 相关事件

- `start_asr`: 开始语音识别
- `audio_data`: 发送音频数据
- `stop_asr`: 停止语音识别
- `asr_partial_result`: 接收实时识别结果
- `asr_result`: 接收最终识别结果

#### TTS 相关事件

- `start_tts`: 基础TTS合成
- `start_stream_tts`: 开始流式TTS合成
- `stream_text`: 发送流式文本
- `flush_tts_buffer`: 清空TTS缓冲区
- `stop_tts`: 停止TTS合成
- `tts_stream_audio`: 接收TTS音频流

#### LLM 相关事件

- `send_llm_message`: 发送消息给LLM并接收流式响应
- `llm_stream_start`: LLM流式响应开始
- `llm_stream_content`: 接收LLM响应内容片段
- `llm_stream_complete`: LLM流式响应完成
- `llm_error`: LLM处理错误
- `cancel_llm_stream`: 取消LLM流式传输

详细的 LLM WebSocket 使用文档请查看: [LLM_WEBSOCKET_GUIDE.md](./LLM_WEBSOCKET_GUIDE.md)

### 使用示例
### 文本标点接口

提供两种方式为文本添加标点：

- HTTP 接口：

    - 路径：`POST /paddlespeech/text/punctuate`
    - 请求体：`{"text": "待添加标点的文本"}`
    - 响应体：`{"result": {"punc_text": "带标点文本"}}`

    示例：

    ```bash
    curl -X POST \
        -H 'Content-Type: application/json' \
        -d '{"text":"你好 我们今天开会讨论方案"}' \
        http://127.0.0.1:8000/paddlespeech/text/punctuate
    ```

- Socket.IO 事件：

    - 发送事件：`punctuate`，数据：`{"text": "待添加标点的文本"}`
    - 接收事件：
        - 成功：`punctuated`，数据：`{"punc_text": str, "session_id": str}`
        - 失败：`punctuate_error`，数据：`{"error": str}`

标点服务地址可在 `config.py` 中通过 `PUNC_SERVER_CONFIG = {"default_ip": "127.0.0.1", "default_port": 8090}` 配置；若缺省则使用上述默认值。

#### LLM 流式对话示例

```javascript
const socket = io('http://localhost:8008');

// 发送消息
socket.emit('send_llm_message', {
    input_text: "你好,请介绍一下你自己",
    session_id: "my-session"
});

// 接收流式响应
let fullResponse = '';
socket.on('llm_stream_content', (data) => {
    fullResponse += data.content;
    console.log('收到内容:', data.content);
});

socket.on('llm_stream_complete', () => {
    console.log('完整响应:', fullResponse);
});
```

#### 完整的对话 + 语音合成示例

```javascript
// 1. 启动流式TTS
socket.emit('start_stream_tts', { spk_id: 0 });

// 2. 发送消息给LLM
socket.emit('send_llm_message', {
    input_text: "讲一个故事"
});

// 3. 将LLM响应转发给TTS进行语音合成
socket.on('llm_stream_content', (data) => {
    socket.emit('stream_text', { text: data.content });
});

// 4. LLM完成后刷新TTS缓冲区
socket.on('llm_stream_complete', () => {
    socket.emit('flush_tts_buffer');
});
```

更多示例请查看 `llm_websocket_example.html`。

### 文件说明

- `main.py`: 主入口文件
- `web_server.py`: WebSocket 服务器实现
- `config.py`: 配置文件
- `audio_hander.py`: 音频处理器
- `paddlespeech_client.py`: PaddleSpeech 客户端
- `llm_websocket_example.html`: LLM WebSocket 前端示例
- `LLM_WEBSOCKET_GUIDE.md`: LLM WebSocket 详细使用指南

### 架构说明

```
前端 (HTML/JS)
    ↓ WebSocket (Socket.IO)
后端 (FastAPI + Socket.IO)
    ├─→ PaddleSpeech ASR 服务
    ├─→ PaddleSpeech TTS 服务
    └─→ LLM API (SSE流式响应)
```
