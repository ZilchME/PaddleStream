import asyncio

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..services.asr_service import register_asr_handlers, register_punctuate_route
from ..clients.audio_handler import TextHttpHandler
from ..config.settings import (
    CORRECTION_CONFIG_PATH,
    LLM_API_CONFIG,
    PUNC_SERVER_CONFIG,
    SOCKETIO_CONFIG,
    SOCKETIO_PATH,
    SYNC_HTTP_TIMEOUT_SECONDS,
    TTS_SERVER_CONFIG,
)
from ..services.correction_config_service import register_correction_config_routes
from ..services.llm_service import register_llm_handlers
from ..core.logging_utils import get_logger
from ..clients.paddlespeech_client import ASROnlineClientExecutor, TTSWebServerExecutor
from ..core.session_manager import SessionManager
from ..services.tts_service import _graceful_tts_session_cleanup, register_tts_handlers

logger = get_logger("paddlestream.web")

app = FastAPI()

_allowed_origins = SOCKETIO_CONFIG.get("cors_allowed_origins", ["*"])
if isinstance(_allowed_origins, str):
    _allowed_origins = ["*"] if _allowed_origins == "*" else [_allowed_origins]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sio = socketio.AsyncServer(
    async_mode=SOCKETIO_CONFIG["async_mode"],
    cors_allowed_origins=SOCKETIO_CONFIG["cors_allowed_origins"],
)
socket_app = socketio.ASGIApp(sio, app, socketio_path=SOCKETIO_PATH)

tts_executor = TTSWebServerExecutor(
    server_ip=TTS_SERVER_CONFIG["default_ip"],
    port=TTS_SERVER_CONFIG["default_port"],
    endpoint=TTS_SERVER_CONFIG["endpoint"],
)

punc_client = TextHttpHandler(
    server_ip=PUNC_SERVER_CONFIG.get("default_ip"),
    port=PUNC_SERVER_CONFIG.get("default_port"),
    timeout=SYNC_HTTP_TIMEOUT_SECONDS,
)

session_manager = SessionManager()
asr_client = ASROnlineClientExecutor()

register_punctuate_route(app, punc_client, logger)
register_correction_config_routes(app, CORRECTION_CONFIG_PATH, logger)
register_asr_handlers(sio, session_manager, asr_client, logger)
register_tts_handlers(sio, session_manager, tts_executor, logger)
register_llm_handlers(sio, session_manager, LLM_API_CONFIG, logger)


@app.get("/")
async def root():
    return {"message": "PaddleStream API 服务运行中"}


@sio.event
async def connect(sid, environ):
    logger.info("Client connected: %s", sid)


@sio.event
async def disconnect(sid):
    logger.info("Client disconnected: %s", sid)

    if session_manager.has_asr_session(sid):
        asr_session = session_manager.pop_asr_session(sid)
        if asr_session:
            asr_session.stop_processing()

    buffer_session = session_manager.get_tts_buffer_session(sid)
    if buffer_session:
        if buffer_session.is_processing:
            logger.info("等待TTS会话 %s 的剩余合成完成...", sid)
            buffer_session.stop_accepting_new_text = True
            asyncio.create_task(_graceful_tts_session_cleanup(sid, session_manager, logger))
        else:
            buffer_session.stop_processing()
            session_manager.pop_tts_buffer_session(sid)

    tts_executor.remove_session(sid)
