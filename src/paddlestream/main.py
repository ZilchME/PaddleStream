import sys

import uvicorn

from .config.settings import (
    WEB_SERVER_CONFIG,
    missing_required_config_items,
    optional_config_summary,
)
from .core.logging_utils import get_logger
from .api.server import socket_app

logger = get_logger("paddlestream.main")


def main() -> None:
    missing = missing_required_config_items()
    if missing:
        logger.error("检测到未配置的必填项，请先完善 `.env`：")
        for key in missing:
            logger.error("- %s", key)
        logger.error("可先复制 `.env.example` 到 `.env`，再逐项填写。")
        sys.exit(1)

    optional = optional_config_summary()
    missing_optional = [key for key, state in optional.items() if state == "missing"]
    if missing_optional:
        logger.warning("以下可选项未配置，对应功能将不可用或需要手动关闭：")
        for key in missing_optional:
            logger.warning("- %s", key)

    try:
        logger.info("请确保 PaddleSpeech 相关服务器已启动:")
        logger.info("=" * 50)
        uvicorn.run(
            socket_app,
            host=WEB_SERVER_CONFIG["host"],
            port=WEB_SERVER_CONFIG["port"],
        )
    except ImportError as e:
        logger.error("错误: 缺少依赖包")
        logger.error("详细错误: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.error("启动Web服务器失败: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
