# StreamASR - 流式语音识别与语音合成服务

## 新增功能：流式TTS Web服务

本项目现在支持通过Web界面进行流式TTS（文本转语音）合成。

### 功能特点

1. **流式合成**：实时接收TTS服务器生成的音频数据块
2. **Web界面**：通过浏览器进行语音合成操作
3. **实时反馈**：显示合成进度和统计信息
4. **音频播放**：支持在线播放合成的音频
5. **音频下载**：支持下载WAV格式的音频文件
6. **多说话人**：支持选择不同的说话人ID

### 架构说明

```
Web客户端 <--Socket.IO--> Web服务器 <--WebSocket--> PaddleSpeech TTS服务器
```

- **Web客户端**：浏览器中的JavaScript应用
- **Web服务器**：基于FastAPI和Socket.IO的中间层服务
- **TTS服务器**：PaddleSpeech TTS流式服务

### 使用方法

1. **启动TTS服务器**
   ```bash
   # 首先启动PaddleSpeech TTS服务器（端口8092）
   paddlespeech_server start --config_file ./tts_online_application.yaml
   ```

2. **启动Web服务器**
   ```bash
   python web_server.py
   ```

3. **访问TTS测试页面**
   打开浏览器访问：`http://localhost:8000/tts`

### Socket.IO事件接口

#### 客户端发送事件

- **start_tts**：开始TTS合成
  ```javascript
  socket.emit('start_tts', {
      text: "要合成的文本",
      spk_id: 0  // 说话人ID
  });
  ```

- **stop_tts**：停止TTS合成
  ```javascript
  socket.emit('stop_tts');
  ```

#### 服务器发送事件

- **tts_stream**：流式音频数据
  ```javascript
  socket.on('tts_stream', (data) => {
      if (data.type === 'audio_chunk') {
          // 处理音频数据块
          console.log(`音频块 ${data.chunk_index}:`, data.audio_data);
      } else if (data.type === 'synthesis_complete') {
          // 合成完成
          console.log('合成完成:', data);
      }
  });
  ```

- **tts_completed**：合成任务完全完成
- **tts_error**：合成错误
- **tts_stopped**：合成已停止

### 配置

在 `config.py` 中配置TTS服务器：

```python
TTS_SERVER_CONFIG = {
    "default_ip": "127.0.0.1",
    "default_port": 8092,
    "endpoint": "/paddlespeech/tts/streaming",
}
```

### 代码结构

- **TTSWebServerExecutor**：TTS Web服务执行器，管理多个TTS会话
- **WebTTSSession**：单个TTS会话处理类
- **Socket.IO事件处理**：在 `web_server.py` 中处理TTS相关的Socket.IO事件

### 音频格式

- 服务器返回Base64编码的PCM音频数据
- 客户端将PCM数据转换为WAV格式进行播放和下载
- 默认采样率：24000Hz
- 默认格式：16位单声道

### 示例代码

```python
# 创建TTS服务执行器
tts_executor = TTSWebServerExecutor(
    server_ip="127.0.0.1",
    port=8092
)

# 异步合成文本
async def synthesize_text():
    async def stream_callback(chunk_data):
        # 处理流式音频数据
        print(f"接收音频块: {chunk_data['chunk_index']}")
    
    result = await tts_executor.synthesize_text(
        session_id="test_session",
        text="你好，这是测试文本",
        spk_id=0,
        stream_callback=stream_callback
    )
    print("合成结果:", result)
```

### 注意事项

1. 确保PaddleSpeech TTS服务器正在运行
2. 检查防火墙设置，确保端口8000和8092可访问
3. 大量文本合成时注意服务器性能
4. 音频数据会暂存在内存中，长时间合成需要注意内存使用
