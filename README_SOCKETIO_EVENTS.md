# Socket.IO 事件接口文档

本文档描述了StreamASR系统中所有可用的Socket.IO事件端点，包括基础TTS和新增的流式TTS功能。

## 连接事件

### connect
- **方向**: 服务器 → 客户端
- **触发**: 客户端成功连接到服务器时
- **数据**: 无
- **说明**: 服务器自动响应连接事件

### connected
- **方向**: 服务器 → 客户端
- **触发**: 客户端连接成功后
- **数据格式**:
```json
{
    "session_id": "client_session_id"
}
```

### disconnect
- **方向**: 客户端 → 服务器
- **触发**: 客户端断开连接时
- **数据**: 无
- **说明**: 服务器会自动清理相关会话资源

---

## ASR (语音识别) 事件

### start_asr
- **方向**: 客户端 → 服务器
- **数据**: 无
- **功能**: 启动ASR语音识别会话
- **响应**: `asr_started`

### asr_started
- **方向**: 服务器 → 客户端
- **数据格式**:
```json
{
    "session_id": "client_session_id"
}
```

### audio_data
- **方向**: 客户端 → 服务器
- **数据格式**:
```json
{
    "audio": "base64_encoded_audio_data" // 或音频数组
}
```
- **功能**: 发送音频数据进行实时识别

### asr_partial_result
- **方向**: 服务器 → 客户端
- **数据格式**:
```json
{
    "result": "部分识别结果",
    "type": "partial",
    "session_id": "client_session_id",
    "timestamp": 1640995200.123
}
```

### asr_result
- **方向**: 服务器 → 客户端
- **数据格式**:
```json
{
    "status": "completed",
    "result": "最终识别结果",
    "session_id": "client_session_id"
}
```

### stop_asr
- **方向**: 客户端 → 服务器
- **数据**: 无
- **功能**: 停止ASR识别
- **响应**: `asr_stopped`

### asr_stopped
- **方向**: 服务器 → 客户端
- **数据格式**:
```json
{
    "session_id": "client_session_id"
}
```

### asr_error
- **方向**: 服务器 → 客户端
- **数据格式**:
```json
{
    "error": "错误描述",
    "session_id": "client_session_id"
}
```

---

## TTS (语音合成) 事件

### 基础TTS事件

#### start_tts
- **方向**: 客户端 → 服务器
- **数据格式**:
```json
{
    "text": "要合成的文本",
    "spk_id": 0
}
```
- **功能**: 开始TTS语音合成（一次性合成完整文本）

#### tts_stream
- **方向**: 服务器 → 客户端
- **数据格式**:
```json
{
    "type": "audio_chunk",
    "session_id": "client_session_id",
    "audio_data": "base64_encoded_audio",
    "chunk_index": 1,
    "timestamp": 1640995200.123
}
```
或
```json
{
    "type": "synthesis_complete",
    "session_id": "client_session_id",
    "total_time": 2.5,
    "total_chunks": 10,
    "first_chunk_time": 0.3
}
```

#### tts_completed
- **方向**: 服务器 → 客户端
- **数据格式**:
```json
{
    "status": "completed",
    "total_time": 2.5,
    "total_chunks": 10
}
```

#### stop_tts
- **方向**: 客户端 → 服务器
- **数据**: 无
- **功能**: 停止TTS合成

#### tts_stopped
- **方向**: 服务器 → 客户端
- **数据格式**:
```json
{
    "session_id": "client_session_id"
}
```

#### tts_error
- **方向**: 服务器 → 客户端
- **数据格式**:
```json
{
    "error": "错误描述"
}
```

---

## 流式TTS事件

### start_stream_tts
- **方向**: 客户端 → 服务器
- **数据格式**:
```json
{
    "spk_id": 0,
    "max_buffer_size": 1000
}
```
- **功能**: 启动流式TTS会话，支持文本缓冲和分句处理
- **响应**: `stream_tts_started`

### stream_tts_started
- **方向**: 服务器 → 客户端
- **数据格式**:
```json
{
    "session_id": "client_session_id",
    "spk_id": 0,
    "max_buffer_size": 1000
}
```

### stream_text
- **方向**: 客户端 → 服务器
- **数据格式**:
```json
{
    "text": "文本片段"
}
```
- **功能**: 发送文本片段到缓冲区，系统自动进行分句处理
- **响应**: `tts_buffer_status`

### tts_buffer_status
- **方向**: 服务器 → 客户端
- **数据格式**:
```json
{
    "status": {
        "session_id": "client_session_id",
        "buffer_length": 50,
        "pending_sentences": 2,
        "total_sentences": 5,
        "processed_sentences": 3,
        "is_processing": true
    },
    "new_sentences": 1
}
```

### flush_tts_buffer
- **方向**: 客户端 → 服务器
- **数据**: 无
- **功能**: 强制清空缓冲区，将剩余文本作为句子处理
- **响应**: `tts_buffer_flushed`

### tts_buffer_flushed
- **方向**: 服务器 → 客户端
- **数据格式**:
```json
{
    "status": {
        "session_id": "client_session_id",
        "buffer_length": 0,
        "pending_sentences": 1,
        "total_sentences": 6,
        "processed_sentences": 5,
        "is_processing": true
    },
    "remaining_sentences": 1,
    "sentences": ["剩余的文本片段"]
}
```

### get_tts_status
- **方向**: 客户端 → 服务器
- **数据**: 无
- **功能**: 获取当前TTS会话状态
- **响应**: `tts_status`

### tts_status
- **方向**: 服务器 → 客户端
- **数据格式**:
```json
{
    "session_id": "client_session_id",
    "buffer_length": 20,
    "pending_sentences": 1,
    "total_sentences": 3,
    "processed_sentences": 2,
    "is_processing": true
}
```
或（会话不存在时）:
```json
{
    "session_id": "client_session_id",
    "exists": false
}
```

---

## 通用错误事件

### error
- **方向**: 服务器 → 客户端
- **数据格式**:
```json
{
    "message": "错误描述"
}
```
- **触发**: 通用错误情况

---

## 使用示例

### ASR使用流程
```javascript
// 1. 连接
socket.on('connected', (data) => {
    console.log('连接成功:', data.session_id);
});

// 2. 启动ASR
socket.emit('start_asr');

// 3. 监听结果
socket.on('asr_partial_result', (data) => {
    console.log('部分结果:', data.result);
});

socket.on('asr_result', (data) => {
    console.log('最终结果:', data.result);
});

// 4. 发送音频数据
socket.emit('audio_data', {
    audio: base64AudioData
});

// 5. 停止识别
socket.emit('stop_asr');
```

### 基础TTS使用流程
```javascript
// 1. 开始合成
socket.emit('start_tts', {
    text: '你好，世界！',
    spk_id: 0
});

// 2. 监听音频流
socket.on('tts_stream', (data) => {
    if (data.type === 'audio_chunk') {
        playAudioChunk(data.audio_data);
    } else if (data.type === 'synthesis_complete') {
        console.log('合成完成');
    }
});
```

### 流式TTS使用流程
```javascript
// 1. 启动流式TTS
socket.emit('start_stream_tts', {
    spk_id: 0,
    max_buffer_size: 1000
});

// 2. 监听启动确认
socket.on('stream_tts_started', (data) => {
    console.log('流式TTS已启动');
});

// 3. 逐步发送文本
socket.emit('stream_text', { text: '你好，' });
socket.emit('stream_text', { text: '这是一个' });
socket.emit('stream_text', { text: '测试。' });

// 4. 监听缓冲区状态
socket.on('tts_buffer_status', (data) => {
    console.log('缓冲区状态:', data.status);
});

// 5. 监听合成的音频
socket.on('tts_stream', (data) => {
    if (data.type === 'audio_chunk') {
        playAudioChunk(data.audio_data);
        console.log('合成句子:', data.sentence);
    }
});

// 6. 清空剩余缓冲区
socket.emit('flush_tts_buffer');

// 7. 停止
socket.emit('stop_tts');
```

---

## 注意事项

1. **会话管理**: 每个客户端连接对应独立的会话，会话ID在连接建立时分配
2. **资源清理**: 客户端断开连接时，服务器会自动清理所有相关资源
3. **错误处理**: 建议监听相应的错误事件来处理异常情况
4. **音频格式**: 
   - 输入音频: 支持Base64编码或数组格式
   - 输出音频: Base64编码的音频数据，需要客户端解码后播放
5. **流式TTS分句规则**:
   - 主要分句符: 句号(。.)、问号(?？)、感叹号(!！)、换行符(\n)
   - 次要分句符: 逗号(,，)、分号(;；)
   - 缓冲区过大时会强制分句
6. **性能建议**:
   - 音频数据建议分块发送，避免单次发送过大的数据
   - 流式文本建议适当间隔发送，避免过于频繁的请求
