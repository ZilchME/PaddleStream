# PaddleStream

PaddleStream 是一个面向 PaddleSpeech 的流式接入层，用于把 ASR、TTS 和 LLM SSE 能力统一封装成 FastAPI + Socket.IO 服务，方便前端实时交互。

> 运行环境要求：Python 3.11 或更高版本。

## 主要能力

- 流式 ASR 转写，支持实时结果回传
- 流式 TTS 合成，支持分句缓冲和回调推送
- LLM SSE 转发，支持流式内容推送和取消
- 文本标点补全接口
- 统一的会话管理与配置加载

## 快速开始

1. 安装依赖。

```bash
uv sync
```

1. 准备环境变量。

```bash
cp .env.example .env
```

1. 启动 PaddleSpeech 服务。

```bash
paddlespeech_server start --config_file configs/application.yaml
```

1. 启动 PaddleStream。

```bash
uv run paddlestream
```

也可以直接运行：

```bash
python -m paddlestream
```

## 配置

运行参数通过 `.env` 配置，缺失时启动会明确提示。

### 必填项

- `PADDLESTREAM_WEB_HOST`
- `PADDLESTREAM_WEB_PORT`
- `PADDLESTREAM_ASR_SERVER_IP`
- `PADDLESTREAM_ASR_SERVER_PORT`
- `PADDLESTREAM_ASR_SERVER_ENDPOINT`
- `PADDLESTREAM_TTS_SERVER_IP`
- `PADDLESTREAM_TTS_SERVER_PORT`
- `PADDLESTREAM_TTS_SERVER_ENDPOINT`
- `PADDLESTREAM_SYNC_HTTP_TIMEOUT_SECONDS`

### 可选项

- `PADDLESTREAM_LLM_API_URL`
- `PADDLESTREAM_LLM_API_TIMEOUT`
- `PADDLESTREAM_PUNC_SERVER_IP`
- `PADDLESTREAM_PUNC_SERVER_PORT`
- `PADDLESTREAM_CORRECTION_CONFIG_PATH`
- `PADDLESTREAM_PROJECT_DIR`

### 配置说明

| 变量 | 说明 |
| --- | --- |
| `PADDLESTREAM_PROJECT_DIR` | 指定项目根目录，`.env` 和 `data/` 会从这里解析 |
| `PADDLESTREAM_CORRECTION_CONFIG_PATH` | 运行时纠错配置路径，默认保存到 `data/correction_config.json` |
| `PADDLESTREAM_LLM_API_URL` | LLM SSE 地址，不配置则禁用 LLM 流式功能 |
| `PADDLESTREAM_PUNC_SERVER_IP` / `PADDLESTREAM_PUNC_SERVER_PORT` | 标点服务地址，不配置则直接返回原文 |

更多说明见：

- [架构说明](docs/architecture.md)
- [API 与事件](docs/api.md)
- [部署说明](docs/deployment.md)
- [LLM 流式说明](docs/llm_websocket_guide.md)

## 目录结构

```text
src/paddlestream/    核心业务代码
configs/             PaddleSpeech 配置和示例配置
docs/                架构、API、部署文档
data/                运行时生成的数据
```

## 运行时文件

- 纠错配置默认写入 `data/correction_config.json`
- 该文件不会提交到仓库

## 使用提示

- 需要先启动 PaddleSpeech ASR / TTS 服务
- 如果需要 LLM 流式功能，需要额外配置 `PADDLESTREAM_LLM_API_URL` 和 `PADDLESTREAM_LLM_API_TIMEOUT`
- 如果需要标点补全，需要额外配置标点服务地址

## License

[MIT](LICENSE)
