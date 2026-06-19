# 架构说明

PaddleStream 的职责是把 PaddleSpeech 的能力封装成一个更容易接入前端的统一服务。

## 组件

- `src/paddlestream/api/server.py`
  - FastAPI + Socket.IO 主入口
  - 对外暴露 HTTP 和 WebSocket 事件
- `src/paddlestream/clients/paddlespeech_client.py`
  - ASR / TTS 的客户端封装
- `src/paddlestream/clients/audio_handler.py`
  - 音频缓冲、PaddleSpeech WebSocket 通信、标点补全调用
- `src/paddlestream/core/session_manager.py`
  - 统一管理 ASR、TTS、LLM 会话状态
- `src/paddlestream/config/settings.py`
  - 环境变量、`.env`、默认配置加载

## 数据流

1. 前端通过 Socket.IO 发送 ASR / TTS / LLM 请求
2. 后端把请求转发给 PaddleSpeech 或 LLM API
3. 流式结果再通过 Socket.IO 回推给前端
4. 会话状态由 `SessionManager` 集中管理，避免全局字典散落在多个模块

## 设计原则

- 运行时状态不提交到仓库
- 外部依赖统一超时处理
- 配置集中在 `.env` 和 `config/settings.py`
- 文档、示例、源码分层
