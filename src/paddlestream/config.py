from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


PROJECT_DIR = Path(os.getenv("PADDLESTREAM_PROJECT_DIR", str(Path.cwd()))).resolve()
ENV_FILE = PROJECT_DIR / ".env"
DEFAULT_CORRECTION_CONFIG_PATH = PROJECT_DIR / "data" / "correction_config.json"


def _load_dotenv(path: Path) -> None:
    """Load a minimal .env file without requiring extra dependencies."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue

        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

        os.environ[key] = value


def _env_str(key: str) -> Optional[str]:
    value = os.getenv(key)
    return value if value not in (None, "") else None


def _env_optional_str(key: str) -> Optional[str]:
    value = os.getenv(key)
    if value is None or value == "":
        return None
    if value.lower() in {"none", "null"}:
        return None
    return value


def _env_int(key: str) -> Optional[int]:
    value = os.getenv(key)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


_load_dotenv(ENV_FILE)


WEB_SERVER_CONFIG = {
    "host": _env_str("PADDLESTREAM_WEB_HOST"),
    "port": _env_int("PADDLESTREAM_WEB_PORT"),
}

SYNC_HTTP_TIMEOUT_SECONDS = _env_int("PADDLESTREAM_SYNC_HTTP_TIMEOUT_SECONDS")

ASR_SERVER_CONFIG = {
    "default_ip": _env_str("PADDLESTREAM_ASR_SERVER_IP"),
    "default_port": _env_int("PADDLESTREAM_ASR_SERVER_PORT"),
    "endpoint": _env_str("PADDLESTREAM_ASR_SERVER_ENDPOINT"),
}

TTS_SERVER_CONFIG = {
    "default_ip": _env_str("PADDLESTREAM_TTS_SERVER_IP"),
    "default_port": _env_int("PADDLESTREAM_TTS_SERVER_PORT"),
    "endpoint": _env_str("PADDLESTREAM_TTS_SERVER_ENDPOINT"),
}

PUNC_SERVER_CONFIG = {
    "default_ip": _env_optional_str("PADDLESTREAM_PUNC_SERVER_IP"),
    "default_port": _env_int("PADDLESTREAM_PUNC_SERVER_PORT"),
}

SOCKETIO_CONFIG = {
    "cors_allowed_origins": os.getenv("PADDLESTREAM_SOCKETIO_CORS_ALLOWED_ORIGINS", "*"),
    "async_mode": "asgi",
}

SOCKETIO_PATH = os.getenv("PADDLESTREAM_SOCKETIO_PATH", "/socket.io/")

LLM_API_CONFIG = {
    "url": _env_optional_str("PADDLESTREAM_LLM_API_URL"),
    "timeout": _env_int("PADDLESTREAM_LLM_API_TIMEOUT"),
}

CORRECTION_CONFIG_PATH = Path(
    _env_optional_str("PADDLESTREAM_CORRECTION_CONFIG_PATH")
    or str(DEFAULT_CORRECTION_CONFIG_PATH)
)


def _format_config_state(value: Optional[object]) -> str:
    return "missing" if value in (None, "") else "set"


def missing_required_config_items() -> list[str]:
    required_items = {
        "PADDLESTREAM_WEB_HOST": WEB_SERVER_CONFIG["host"],
        "PADDLESTREAM_WEB_PORT": WEB_SERVER_CONFIG["port"],
        "PADDLESTREAM_ASR_SERVER_IP": ASR_SERVER_CONFIG["default_ip"],
        "PADDLESTREAM_ASR_SERVER_PORT": ASR_SERVER_CONFIG["default_port"],
        "PADDLESTREAM_TTS_SERVER_IP": TTS_SERVER_CONFIG["default_ip"],
        "PADDLESTREAM_TTS_SERVER_PORT": TTS_SERVER_CONFIG["default_port"],
        "PADDLESTREAM_ASR_SERVER_ENDPOINT": ASR_SERVER_CONFIG["endpoint"],
        "PADDLESTREAM_TTS_SERVER_ENDPOINT": TTS_SERVER_CONFIG["endpoint"],
        "PADDLESTREAM_SYNC_HTTP_TIMEOUT_SECONDS": SYNC_HTTP_TIMEOUT_SECONDS,
    }

    return [key for key, value in required_items.items() if value in (None, "")]


def optional_config_summary() -> dict[str, str]:
    return {
        "PADDLESTREAM_PUNC_SERVER_IP": _format_config_state(PUNC_SERVER_CONFIG["default_ip"]),
        "PADDLESTREAM_PUNC_SERVER_PORT": _format_config_state(PUNC_SERVER_CONFIG["default_port"]),
        "PADDLESTREAM_LLM_API_URL": _format_config_state(LLM_API_CONFIG["url"]),
        "PADDLESTREAM_LLM_API_TIMEOUT": _format_config_state(LLM_API_CONFIG["timeout"]),
    }
