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

`stop_asr` 停止接收新音频，已排队的音频会继续发送到 PaddleSpeech。
`asr_stopped` 仅确认停止输入；客户端应等待 `asr_result` 获取最终结果。
收到上游 `signal=finished` 后才返回最终结果，等待期间的中间结果仍通过
`asr_partial_result` 推送。发送结束信号后默认最多等待 30 秒，超时或连接异常
通过 `error` 事件报告，不把中间结果当成成功完成。
识别文本重复不会自动结束会话。

### TTS

- `start_tts`
- `start_stream_tts`
- `stream_text`
- `flush_tts_buffer`
- `stop_tts`
- `tts_stream_audio`

`start_stream_tts` 的 `max_buffer_size` 默认为 1000，必须是正整数，支持 1、2、3
等小缓冲值。非法参数通过 `tts_error` 报告，已有 TTS 缓冲会话不受影响。

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
