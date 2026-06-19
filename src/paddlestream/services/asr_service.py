import asyncio
import base64
from typing import Any, Dict

from fastapi import Body, FastAPI, HTTPException

from ..clients.audio_handler import WebSocketAudioHandler
from ..config.settings import (
    ASR_SERVER_CONFIG,
    PUNC_SERVER_CONFIG,
    SYNC_HTTP_TIMEOUT_SECONDS,
)


def register_punctuate_route(app: FastAPI, punc_client, logger) -> None:
    """注册文本标点 HTTP 接口。"""

    @app.post("/paddlespeech/text/punctuate")
    async def punctuate_text(body: Dict[str, Any] = Body(...)):
        text = (body or {}).get("text", "")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=400, detail="'text' 字段不能为空")

        loop = asyncio.get_running_loop()
        try:
            punc_text = await loop.run_in_executor(None, lambda: punc_client.run(text))
        except Exception as e:
            punc_text = text
            return {"result": {"punc_text": punc_text}, "warning": str(e)}

        return {"result": {"punc_text": punc_text}}


def register_asr_handlers(
    sio,
    session_manager,
    asr_client,
    logger,
) -> None:
    """注册 ASR 相关 Socket.IO 事件。"""

    @sio.event
    async def start_asr(sid):
        logger.info("Starting ASR for session: %s", sid)
        asr_session = WebSocketAudioHandler(sample_rate=16000, chunk_size=1024)
        session_manager.set_asr_session(sid, asr_session)

        asr_session.start_processing()
        asyncio.create_task(process_asr_async(sid, asr_session))
        logger.info("Started recording for client %s", sid)

        await sio.emit("asr_started", {"session_id": sid}, room=sid)

    async def process_asr_async(sid, audio_handler):
        try:
            loop = asyncio.get_running_loop()

            def real_time_callback(result, result_type="partial"):
                async def send_result():
                    await sio.emit(
                        "asr_partial_result",
                        {"result": result, "type": result_type, "session_id": sid},
                        room=sid,
                    )

                asyncio.run_coroutine_threadsafe(send_result(), loop)

            result = await loop.run_in_executor(
                None,
                lambda: asr_client.process_websocket_audio(
                    audio_handler=audio_handler,
                    server_ip=ASR_SERVER_CONFIG["default_ip"],
                    port=ASR_SERVER_CONFIG["default_port"],
                    endpoint=ASR_SERVER_CONFIG["endpoint"],
                    punc_server_ip=PUNC_SERVER_CONFIG.get("default_ip"),
                    punc_server_port=PUNC_SERVER_CONFIG.get("default_port"),
                    request_timeout=SYNC_HTTP_TIMEOUT_SECONDS,
                    real_time_callback=real_time_callback,
                ),
            )

            await sio.emit(
                "asr_result",
                {"status": "completed", "result": result, "session_id": sid},
                room=sid,
            )
            logger.info("Final result for %s: %s", sid, result)
        except Exception as e:
            logger.error("ASR processing error: %s", e)
            await sio.emit("error", {"message": f"ASR processing error: {str(e)}"}, room=sid)

    @sio.event
    async def audio_data(sid, data):
        asr_session = session_manager.get_asr_session(sid)
        if not asr_session:
            await sio.emit("error", {"message": "ASR session not found"}, room=sid)
            return

        try:
            if isinstance(data, dict) and "audio" in data:
                audio_bytes = base64.b64decode(data["audio"])
                asr_session.add_audio_data(audio_bytes)
            elif isinstance(data, bytes):
                asr_session.add_audio_data(data)
            else:
                logger.warning("Unexpected audio data format from %s: %s", sid, type(data))
        except Exception as e:
            logger.error("Error processing audio data: %s", e)
            await sio.emit("error", {"message": f"Audio processing error: {str(e)}"}, room=sid)

    @sio.event
    async def stop_asr(sid):
        asr_session = session_manager.pop_asr_session(sid)
        if asr_session:
            asr_session.stop_processing()
            await sio.emit("asr_stopped", {"session_id": sid}, room=sid)
        else:
            await sio.emit("error", {"message": "音频处理器未找到"}, room=sid)
