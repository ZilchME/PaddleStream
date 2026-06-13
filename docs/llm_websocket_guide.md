# LLM 流式说明

PaddleStream 通过 `send_llm_message` 接收前端输入，再把 LLM 的 SSE 流转发成 Socket.IO 事件。

## 基本流程

1. 前端发送 `send_llm_message`
2. 后端请求 `PADDLESTREAM_LLM_API_URL`
3. 后端不断推送 `llm_stream_content`
4. 流结束后发送 `llm_stream_complete`

## 取消流

发送 `cancel_llm_stream`，并带上目标 `session_id`。

## 常见约定

- `session_id` 应该稳定且唯一
- 前端收到 `llm_stream_content` 后可立即渲染到 UI
- 若同一 `session_id` 重复发起请求，后端会先清理旧流

## 配置

- `PADDLESTREAM_LLM_API_URL`
- `PADDLESTREAM_LLM_API_TIMEOUT`
