import sys

import uvicorn

from .config import (
    WEB_SERVER_CONFIG,
    missing_required_config_items,
    optional_config_summary,
)
from .web_server import socket_app


def main() -> None:
    missing = missing_required_config_items()
    if missing:
        print("检测到未配置的必填项，请先完善 `.env`：")
        for key in missing:
            print(f"- {key}")
        print("可先复制 `.env.example` 到 `.env`，再逐项填写。")
        sys.exit(1)

    optional = optional_config_summary()
    missing_optional = [key for key, state in optional.items() if state == "missing"]
    if missing_optional:
        print("以下可选项未配置，对应功能将不可用或需要手动关闭：")
        for key in missing_optional:
            print(f"- {key}")

    try:
        print("请确保 PaddleSpeech 相关服务器已启动:")
        print("=" * 50)
        uvicorn.run(
            socket_app,
            host=WEB_SERVER_CONFIG["host"],
            port=WEB_SERVER_CONFIG["port"],
        )
    except ImportError as e:
        print("错误: 缺少依赖包")
        print(f"详细错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"启动Web服务器失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
