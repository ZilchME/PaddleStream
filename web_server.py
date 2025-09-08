import asyncio
import base64
import json
import threading
import time
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import socketio
import uvicorn
import numpy as np
from audio_hander import ASRWsAudioHandler
from paddlespeech_client import TTSWebServerExecutor
from config import (
    ASR_SERVER_CONFIG,
    TTS_SERVER_CONFIG,
    WEB_SERVER_CONFIG,
    SOCKETIO_CONFIG,
    SOCKETIO_PATH,
)

# 创建 FastAPI 应用
app = FastAPI()
sio = socketio.AsyncServer(
    async_mode=SOCKETIO_CONFIG["async_mode"],
    cors_allowed_origins=SOCKETIO_CONFIG["cors_allowed_origins"],
)
socket_app = socketio.ASGIApp(sio, app, socketio_path=SOCKETIO_PATH)

# 设置静态文件和模板
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """主页"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/tts", response_class=HTMLResponse)
async def tts_test(request: Request):
    """TTS测试页面"""
    return templates.TemplateResponse("tts_test.html", {"request": request})


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy", "socketio_path": SOCKETIO_PATH}


# 全局变量存储ASR处理器和音频处理器
asr_sessions = {}

# 全局TTS服务执行器
tts_executor = TTSWebServerExecutor(
    server_ip=TTS_SERVER_CONFIG["default_ip"], port=TTS_SERVER_CONFIG["default_port"]
)


class WebASRSession:
    def __init__(
        self, session_id, asr_server_ip=None, asr_server_port=None, endpoint=None
    ):
        self.session_id = session_id
        # 使用配置文件中的默认值
        self.asr_server_ip = asr_server_ip or ASR_SERVER_CONFIG["default_ip"]
        self.asr_server_port = asr_server_port or ASR_SERVER_CONFIG["default_port"]
        self.endpoint = endpoint or ASR_SERVER_CONFIG["endpoint"]

        self.asr_handler = ASRWsAudioHandler(
            url=self.asr_server_ip,
            port=self.asr_server_port,
            endpoint=self.endpoint,
        )
        self.web_audio_handler = self.asr_handler.create_web_audio_handler()
        self.is_processing = False
        self.loop = None
        self.thread = None

    def start_asr_processing(self):
        """在单独线程中启动ASR处理"""
        if self.is_processing:
            return

        self.is_processing = True
        self.thread = threading.Thread(target=self._run_asr_async)
        self.thread.start()

    def _run_asr_async(self):
        """异步运行ASR处理"""
        try:
            # 创建新的事件循环
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            # 定义实时结果回调函数
            def real_time_callback(result, result_type="partial"):
                # 发送实时结果到前端
                async def send_result():
                    await sio.emit(
                        "asr_partial_result",
                        {
                            "result": result,
                            "type": result_type,
                            "session_id": self.session_id,
                            "timestamp": time.time(),
                        },
                        room=self.session_id,
                    )

                asyncio.run_coroutine_threadsafe(send_result(), self.loop)

            # 运行ASR处理，传入回调函数
            result = self.loop.run_until_complete(
                self.asr_handler.run_web_audio(
                    self.web_audio_handler, real_time_callback
                )
            )

            # 发送最终结果到前端
            async def send_final_result():
                await sio.emit(
                    "asr_result",
                    {
                        "status": "completed",
                        "result": result.get("result", "") if result else "",
                        "session_id": self.session_id,
                    },
                    room=self.session_id,
                )

            # asyncio.run_coroutine_threadsafe(send_final_result(), self.loop)
            self.loop.run_until_complete(send_final_result())

        except Exception as e:
            print(f"ASR processing error: {e}")

            async def send_error():
                await sio.emit(
                    "asr_error",
                    {"error": str(e), "session_id": self.session_id},
                    room=self.session_id,
                )

            asyncio.run_coroutine_threadsafe(send_error(), self.loop)
        finally:
            self.is_processing = False
            if self.loop:
                self.loop.close()

    def add_audio_data(self, audio_data):
        """添加音频数据"""
        if self.web_audio_handler:
            self.web_audio_handler.add_audio_data(audio_data)

    def stop_processing(self):
        """停止处理"""
        self.is_processing = False
        if self.web_audio_handler:
            self.web_audio_handler.stop()


@sio.event
async def connect(sid, environ):
    """客户端连接"""
    print(f"Client connected: {sid}")
    await sio.emit("connected", {"session_id": sid}, room=sid)


@sio.event
async def disconnect(sid):
    """客户端断开连接"""
    print(f"Client disconnected: {sid}")

    # 清理ASR会话
    if sid in asr_sessions:
        asr_sessions[sid].stop_processing()
        del asr_sessions[sid]

    # 清理TTS会话
    tts_executor.remove_session(sid)


@sio.event
async def start_asr(sid):
    """开始ASR处理"""
    print(f"Starting ASR for session: {sid}")

    # 从客户端数据中获取服务器配置，如果没有则使用默认配置
    server_ip = None
    server_port = None

    # 创建新的ASR会话
    asr_session = WebASRSession(sid, server_ip, server_port)
    asr_sessions[sid] = asr_session

    # 开始ASR处理
    asr_session.start_asr_processing()

    await sio.emit("asr_started", {"session_id": sid}, room=sid)


@sio.event
async def audio_data(sid, data):
    """处理音频数据"""
    if sid not in asr_sessions:
        await sio.emit("error", {"message": "ASR session not found"}, room=sid)
        return

    try:
        # 解码音频数据
        if "audio" in data:
            if isinstance(data["audio"], str):
                # Base64编码的数据
                audio_bytes = base64.b64decode(data["audio"])
            elif isinstance(data["audio"], list):
                # 数组数据
                audio_bytes = np.array(data["audio"], dtype=np.int16).tobytes()
            else:
                print(f"Unsupported audio data format: {type(data['audio'])}")
                return

            # 添加到ASR处理器
            asr_sessions[sid].add_audio_data(audio_bytes)

    except Exception as e:
        print(f"Error processing audio data: {e}")
        await sio.emit(
            "error", {"message": f"Audio processing error: {str(e)}"}, room=sid
        )


@sio.event
async def stop_asr(sid):
    """停止ASR处理"""
    if sid in asr_sessions:
        asr_sessions[sid].stop_processing()
        await sio.emit("asr_stopped", {"session_id": sid}, room=sid)


@sio.event
async def start_tts(sid, data):
    """开始TTS合成"""
    print(f"Starting TTS for session: {sid}")

    try:
        text = data.get("text", "")
        spk_id = data.get("spk_id", 0)

        if not text:
            await sio.emit("tts_error", {"error": "Text is required"}, room=sid)
            return

        # 定义流式回调函数
        async def stream_callback(chunk_data):
            await sio.emit("tts_stream", chunk_data, room=sid)

        # 开始TTS合成
        result = await tts_executor.synthesize_text(
            session_id=sid, text=text, spk_id=spk_id, stream_callback=stream_callback
        )

        if result["status"] == "completed":
            await sio.emit("tts_completed", result, room=sid)
        else:
            await sio.emit("tts_error", result, room=sid)

    except Exception as e:
        print(f"TTS error: {e}")
        await sio.emit("tts_error", {"error": str(e)}, room=sid)


@sio.event
async def stop_tts(sid):
    """停止TTS合成"""
    print(f"Stopping TTS for session: {sid}")
    tts_executor.remove_session(sid)
    await sio.emit("tts_stopped", {"session_id": sid}, room=sid)


if __name__ == "__main__":
    print("Starting Web ASR Server...")
    print(f"Open http://localhost:{WEB_SERVER_CONFIG['port']} in your browser")
    uvicorn.run(
        socket_app,
        host=WEB_SERVER_CONFIG["host"],
        port=WEB_SERVER_CONFIG["port"],
    )
