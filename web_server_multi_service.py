import asyncio
import base64
import json
import threading
import time
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import socketio
import uvicorn
import numpy as np
from audio_hander import ASRWsAudioHandler
from config import ASR_SERVER_CONFIG, WEB_SERVER_CONFIG, SOCKETIO_CONFIG, SOCKETIO_PATH

# 创建 FastAPI 应用
app = FastAPI(title="StreamASR Multi-Service Server")

# 创建多个Socket.IO实例用于不同服务
sio_instances = {}

def create_socketio_app(service_name, socketio_path):
    """为指定服务创建Socket.IO应用"""
    sio = socketio.AsyncServer(
        async_mode=SOCKETIO_CONFIG["async_mode"],
        cors_allowed_origins=SOCKETIO_CONFIG["cors_allowed_origins"],
    )
    
    # 为每个服务创建独立的会话存储
    service_sessions = {}
    
    @sio.event
    async def connect(sid, environ):
        """客户端连接"""
        print(f"[{service_name}] Client connected: {sid}")
        await sio.emit("connected", {"session_id": sid, "service": service_name}, room=sid)

    @sio.event
    async def disconnect(sid):
        """客户端断开连接"""
        print(f"[{service_name}] Client disconnected: {sid}")
        if sid in service_sessions:
            if hasattr(service_sessions[sid], 'stop_processing'):
                service_sessions[sid].stop_processing()
            del service_sessions[sid]

    # 根据服务类型注册不同的事件处理器
    if service_name == "asr":
        register_asr_events(sio, service_sessions)
    elif service_name == "tts":
        register_tts_events(sio, service_sessions)
    elif service_name == "nlp":
        register_nlp_events(sio, service_sessions)
    
    return sio, service_sessions

def register_asr_events(sio, sessions):
    """注册ASR服务的Socket.IO事件"""
    
    @sio.event
    async def start_asr(sid):
        """开始ASR处理"""
        print(f"[ASR] Starting ASR for session: {sid}")
        
        # 这里使用现有的WebASRSession类
        from web_server import WebASRSession
        asr_session = WebASRSession(sid)
        sessions[sid] = asr_session
        asr_session.start_asr_processing()
        
        await sio.emit("asr_started", {"session_id": sid}, room=sid)

    @sio.event
    async def audio_data(sid, data):
        """处理音频数据"""
        if sid not in sessions:
            await sio.emit("error", {"message": "ASR session not found"}, room=sid)
            return
        
        try:
            if "audio" in data:
                if isinstance(data["audio"], str):
                    audio_bytes = base64.b64decode(data["audio"])
                elif isinstance(data["audio"], list):
                    audio_bytes = np.array(data["audio"], dtype=np.int16).tobytes()
                else:
                    return
                
                sessions[sid].add_audio_data(audio_bytes)
        except Exception as e:
            print(f"[ASR] Error processing audio data: {e}")
            await sio.emit("error", {"message": f"Audio processing error: {str(e)}"}, room=sid)

    @sio.event
    async def stop_asr(sid):
        """停止ASR处理"""
        if sid in sessions:
            sessions[sid].stop_processing()
            await sio.emit("asr_stopped", {"session_id": sid}, room=sid)

def register_tts_events(sio, sessions):
    """注册TTS服务的Socket.IO事件"""
    
    @sio.event
    async def start_tts(sid, data):
        """开始TTS处理"""
        print(f"[TTS] Starting TTS for session: {sid}")
        text = data.get("text", "")
        
        # 这里可以实现TTS逻辑
        # sessions[sid] = TTSSession(sid, text)
        
        await sio.emit("tts_started", {"session_id": sid}, room=sid)
        
        # 模拟TTS处理
        await asyncio.sleep(1)
        await sio.emit("tts_result", {
            "session_id": sid, 
            "audio_url": f"/audio/{sid}.wav",
            "text": text
        }, room=sid)

    @sio.event
    async def stop_tts(sid):
        """停止TTS处理"""
        await sio.emit("tts_stopped", {"session_id": sid}, room=sid)

def register_nlp_events(sio, sessions):
    """注册NLP服务的Socket.IO事件"""
    
    @sio.event
    async def process_text(sid, data):
        """处理文本"""
        print(f"[NLP] Processing text for session: {sid}")
        text = data.get("text", "")
        
        # 这里可以实现NLP逻辑
        # sessions[sid] = NLPSession(sid, text)
        
        await sio.emit("nlp_started", {"session_id": sid}, room=sid)
        
        # 模拟NLP处理
        await asyncio.sleep(0.5)
        await sio.emit("nlp_result", {
            "session_id": sid,
            "analysis": {
                "sentiment": "positive",
                "entities": ["example"],
                "keywords": ["text", "processing"]
            },
            "original_text": text
        }, room=sid)

# 创建默认的ASR服务
sio_asr, asr_sessions = create_socketio_app("asr", SOCKETIO_PATH)
socket_app = socketio.ASGIApp(sio_asr, app, socketio_path=SOCKETIO_PATH)

# 设置静态文件和模板
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """主页"""
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request, 
            "socketio_path": SOCKETIO_PATH,
            "server_host": WEB_SERVER_CONFIG["host"],
            "server_port": WEB_SERVER_CONFIG["port"],
            "service_name": "ASR"
        }
    )

@app.get("/services")
async def list_services():
    """列出所有可用服务"""
    services = {
        "asr": {
            "name": "语音识别",
            "socketio_path": SOCKETIO_PATH,
            "status": "active"
        },
        "tts": {
            "name": "语音合成", 
            "socketio_path": "/tts/socket.io/",
            "status": "available"
        },
        "nlp": {
            "name": "自然语言处理",
            "socketio_path": "/nlp/socket.io/", 
            "status": "available"
        }
    }
    return JSONResponse(services)

@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy", 
        "active_service": "asr",
        "socketio_path": SOCKETIO_PATH,
        "services": ["asr", "tts", "nlp"]
    }

if __name__ == "__main__":
    print("Starting Multi-Service Web Server...")
    print(f"ASR Service: http://localhost:{WEB_SERVER_CONFIG['port']} (Socket.IO: {SOCKETIO_PATH})")
    print(f"Services API: http://localhost:{WEB_SERVER_CONFIG['port']}/services")
    
    uvicorn.run(
        socket_app,
        host=WEB_SERVER_CONFIG["host"],
        port=WEB_SERVER_CONFIG["port"],
        reload=WEB_SERVER_CONFIG["reload"],
    )
