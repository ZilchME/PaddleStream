# 部署说明

## 前置服务

先启动 PaddleSpeech 服务：

```bash
paddlespeech_server start --config_file configs/application.yaml
```

如果需要标点补全，额外启动标点服务。

## 环境准备

```bash
uv sync
cp .env.example .env
```

根据实际环境修改 `.env`。
必填项缺失时，启动命令会直接提示缺失的变量并退出。
默认会按启动目录寻找 `.env` 和 `data/`，如需覆盖可以设置 `PADDLESTREAM_PROJECT_DIR`。

## 启动应用

```bash
uv run paddlestream
```

或者：

```bash
python -m paddlestream
```

## 运行时文件

- 纠错配置默认写到 `data/correction_config.json`
- 该文件不应提交到仓库

## 建议

- 生产环境把 `.env` 放到部署系统或 secret 管理中
- `config/settings.py` 只保留默认值和环境变量解析，不直接写死环境专属参数
