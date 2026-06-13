# API 与事件

## HTTP

### `POST /paddlespeech/text/punctuate`

请求：

```json
{"text":"待添加标点的文本"}
```

响应：

```json
{"result":{"punc_text":"带标点文本"}}
```

### `GET /api/correction-config`

获取当前纠错配置。

### `POST /api/correction-config`

更新纠错配置。

### `DELETE /api/correction-config`

删除运行时纠错配置，恢复默认行为。

## Socket.IO 事件

### ASR

- `start_asr`
- `audio_data`
- `stop_asr`
- `asr_partial_result`
- `asr_result`

### TTS

- `start_tts`
- `start_stream_tts`
- `stream_text`
- `flush_tts_buffer`
- `stop_tts`
- `tts_stream_audio`

### LLM

- `send_llm_message`
- `llm_stream_start`
- `llm_stream_content`
- `llm_stream_complete`
- `llm_error`
- `cancel_llm_stream`

## 约定

- 所有流式消息都绑定 `session_id`
- 会话清理在断开连接和显式停止时执行
- LLM 取消接口支持按传入 `session_id` 取消
