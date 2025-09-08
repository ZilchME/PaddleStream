# 流式TTS语音合成文档

## 概述

本系统支持流式文本到语音（TTS）合成，允许客户端逐步发送文本片段，服务端实时进行分句处理和语音合成。这种方式特别适用于实时聊天、流式翻译等场景。

## 功能特性

### 1. 文本缓冲机制
- 支持流式文本输入，自动累积文本到缓冲区
- 智能分句：支持中文句号（。）、英文句号（.）、问号（？!）、感叹号（！!）、换行符等
- 缓冲区大小限制，防止内存溢出
- 强制分句：当缓冲区过大时按逗号、分号等标点或固定长度分割

### 2. 实时语音合成
- 后台异步处理，不阻塞文本输入
- 按句子顺序合成，保证输出连贯性
- 支持流式音频输出
- 合成状态实时反馈

### 3. 会话管理
- 每个客户端独立的TTS缓冲会话
- 支持会话状态查询
- 自动资源清理

## Socket.IO 事件接口

### 客户端发送事件

#### 1. start_stream_tts - 开始流式TTS
```javascript
socket.emit('start_stream_tts', {
    spk_id: 0,              // 说话人ID，默认0
    max_buffer_size: 1000   // 缓冲区最大字符数，默认1000
});
```

#### 2. stream_text - 发送文本片段
```javascript
socket.emit('stream_text', {
    text: "这是一个文本片段"
});
```

#### 3. flush_tts_buffer - 强制清空缓冲区
```javascript
socket.emit('flush_tts_buffer');
```

#### 4. get_tts_status - 获取TTS状态
```javascript
socket.emit('get_tts_status');
```

#### 5. stop_tts - 停止TTS合成
```javascript
socket.emit('stop_tts');
```

### 服务端回应事件

#### 1. stream_tts_started - 流式TTS启动成功
```javascript
socket.on('stream_tts_started', (data) => {
    console.log('流式TTS已启动:', data);
    // data: { session_id, spk_id, max_buffer_size }
});
```

#### 2. tts_stream - 音频流数据
```javascript
socket.on('tts_stream', (data) => {
    if (data.type === 'audio_chunk') {
        // 处理音频数据
        const audioData = data.audio_data;  // Base64编码的音频
        const sentence = data.sentence;     // 当前合成的句子
        playAudio(audioData);
    } else if (data.type === 'synthesis_complete') {
        console.log('句子合成完成');
    }
});
```

#### 3. tts_buffer_status - 缓冲区状态更新
```javascript
socket.on('tts_buffer_status', (data) => {
    console.log('缓冲区状态:', data.status);
    console.log('新增句子数:', data.new_sentences);
});
```

#### 4. tts_buffer_flushed - 缓冲区已清空
```javascript
socket.on('tts_buffer_flushed', (data) => {
    console.log('缓冲区已清空');
    console.log('剩余句子:', data.remaining_sentences);
});
```

#### 5. tts_status - TTS状态信息
```javascript
socket.on('tts_status', (data) => {
    console.log('TTS状态:', data);
    // data: { session_id, buffer_length, pending_sentences, total_sentences, processed_sentences, is_processing }
});
```

#### 6. tts_error - 错误信息
```javascript
socket.on('tts_error', (data) => {
    console.error('TTS错误:', data.error);
});
```

## 使用示例

### 基本流式TTS使用
```javascript
// 1. 连接Socket.IO
const socket = io('ws://localhost:8000', {
    path: '/socket.io/'
});

// 2. 启动流式TTS
socket.emit('start_stream_tts', {
    spk_id: 0,
    max_buffer_size: 1000
});

// 3. 监听音频流
socket.on('tts_stream', (data) => {
    if (data.type === 'audio_chunk') {
        playAudioChunk(data.audio_data);
    }
});

// 4. 发送文本片段
function sendText(text) {
    socket.emit('stream_text', { text: text });
}

// 5. 使用示例
sendText("你好，");
sendText("我是");
sendText("智能助手。");
sendText("很高兴为您服务！");

// 6. 强制清空剩余缓冲区
socket.emit('flush_tts_buffer');
```

### 实时对话场景
```javascript
// 模拟实时打字效果
const fullText = "这是一段很长的文本，我们将逐字逐句地发送给TTS服务进行合成。";
let currentIndex = 0;

function simulateTyping() {
    if (currentIndex < fullText.length) {
        const chunk = fullText.slice(currentIndex, currentIndex + 3); // 每次发送3个字符
        socket.emit('stream_text', { text: chunk });
        currentIndex += 3;
        setTimeout(simulateTyping, 200); // 200ms间隔
    } else {
        // 文本发送完毕，清空缓冲区
        socket.emit('flush_tts_buffer');
    }
}

// 开始模拟
simulateTyping();
```

## 分句规则

系统使用以下规则进行自动分句：

1. **主要分句符号**：
   - 中文句号：。
   - 英文句号：.
   - 问号：？ ?
   - 感叹号：！ !
   - 换行符：\n

2. **次要分句符号**（缓冲区过大时使用）：
   - 逗号：，,
   - 分号：；;

3. **强制分句**：
   - 当缓冲区超过设定大小的一半时，按固定长度分割

## 性能优化建议

1. **合理设置缓冲区大小**：
   - 较小的缓冲区：响应更快，但可能打断句子
   - 较大的缓冲区：句子完整性更好，但响应略慢

2. **文本发送频率**：
   - 建议每100-500ms发送一次文本片段
   - 避免过于频繁的发送（会增加服务器负载）

3. **及时清空缓冲区**：
   - 在文本发送完毕后立即调用`flush_tts_buffer`
   - 避免最后的文本片段被遗漏

## 注意事项

1. **会话管理**：每个客户端连接对应一个独立的TTS缓冲会话
2. **资源清理**：客户端断开连接时，服务端会自动清理相关资源
3. **错误处理**：建议监听`tts_error`事件以处理可能的错误
4. **音频格式**：返回的音频数据为Base64编码，需要解码后播放

## 故障排除

1. **没有音频输出**：
   - 检查TTS服务是否正常运行
   - 确认`spk_id`是否有效
   - 查看控制台错误信息

2. **文本分句不准确**：
   - 调整`max_buffer_size`参数
   - 确认文本包含适当的标点符号

3. **音频播放断断续续**：
   - 检查网络连接稳定性
   - 优化音频播放缓冲机制
