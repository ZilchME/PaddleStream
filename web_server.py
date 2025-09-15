import asyncio
import base64
import json
import os
import re
import threading
import time
import wave
from typing import Optional, List, Callable, Dict, Any
from queue import Queue, Empty
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


@app.get("/stream-tts", response_class=HTMLResponse)
async def stream_tts_test(request: Request):
    """流式TTS测试页面"""
    return templates.TemplateResponse("stream_tts_test.html", {"request": request})


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

# 全局TTS缓冲会话管理器
tts_buffer_sessions = {}


class TTSBufferSession:
    """TTS缓冲会话类，支持流式文本输入和实时语音合成"""

    def __init__(self, session_id: str, spk_id: int = 0, max_buffer_size: int = 1000):
        self.session_id = session_id
        self.spk_id = spk_id
        self.max_buffer_size = max_buffer_size

        # 文本缓冲区
        self.text_buffer = ""
        self.pending_sentences = Queue()  # 待合成的句子队列

        # 分句规则：中文句号、英文句号、问号、感叹号、换行符
        self.sentence_endings = re.compile(r"[。！？\.\!\?\n]+")

        # 合成状态
        self.is_processing = False
        self.synthesis_thread = None
        self.stop_synthesis = False

        # 合成锁将在工作线程中创建
        self.synthesis_lock = None
        self.current_synthesizing_sentence = None

        # 回调函数
        self.stream_callback: Optional[Callable] = None

        # 统计信息
        self.total_sentences = 0
        self.processed_sentences = 0

    def set_stream_callback(self, callback: Callable):
        """设置流式音频数据回调函数"""
        self.stream_callback = callback

    def add_text(self, text: str) -> List[str]:
        """
        添加文本到缓冲区，自动处理分句

        Args:
            text (str): 新增的文本片段

        Returns:
            List[str]: 本次提取出的完整句子列表
        """
        self.text_buffer += text

        # 检查缓冲区大小
        if len(self.text_buffer) > self.max_buffer_size:
            # 如果缓冲区过大，强制分句（防止内存溢出）
            sentences = self._force_split_buffer()
        else:
            # 正常分句处理
            sentences = self._extract_sentences()

        # 将提取的句子加入待合成队列
        for sentence in sentences:
            if sentence.strip():  # 忽略空字符串
                self.pending_sentences.put(sentence.strip())
                self.total_sentences += 1

        return sentences

    def _extract_sentences(self) -> List[str]:
        """从缓冲区提取完整的句子"""
        sentences = []

        # 使用正则表达式分割句子
        parts = self.sentence_endings.split(self.text_buffer)

        # 如果有多个部分，说明找到了句子分隔符
        if len(parts) > 1:
            # 前面的部分都是完整句子
            sentences = parts[:-1]
            # 最后一部分可能是不完整的句子，保留在缓冲区
            self.text_buffer = parts[-1]

        return sentences

    def _force_split_buffer(self) -> List[str]:
        """强制分割缓冲区（当缓冲区过大时）"""
        sentences = []

        # 首先尝试正常分句
        normal_sentences = self._extract_sentences()
        sentences.extend(normal_sentences)

        # 如果缓冲区仍然过大，按固定长度分割
        if len(self.text_buffer) > self.max_buffer_size // 2:
            # 按逗号、分号等标点分割
            comma_parts = re.split(r"[，,；;]", self.text_buffer)
            if len(comma_parts) > 1:
                sentences.extend(comma_parts[:-1])
                self.text_buffer = comma_parts[-1]
            else:
                # 最后手段：按固定长度强制分割
                chunk_size = self.max_buffer_size // 4
                while len(self.text_buffer) > chunk_size:
                    sentences.append(self.text_buffer[:chunk_size])
                    self.text_buffer = self.text_buffer[chunk_size:]

        return sentences

    def flush_buffer(self) -> List[str]:
        """
        清空缓冲区，将剩余文本作为句子处理

        Returns:
            List[str]: 剩余的文本片段列表
        """
        sentences = []

        if self.text_buffer.strip():
            sentences.append(self.text_buffer.strip())
            self.pending_sentences.put(self.text_buffer.strip())
            self.total_sentences += 1
            self.text_buffer = ""

        return sentences

    def start_synthesis(self):
        """开始后台合成处理"""
        if self.is_processing:
            return

        self.is_processing = True
        self.stop_synthesis = False
        self.synthesis_thread = threading.Thread(target=self._synthesis_worker)
        self.synthesis_thread.start()

    def _synthesis_worker(self):
        """后台合成工作线程"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # 在工作线程中创建异步锁
        self.synthesis_lock = asyncio.Lock()

        try:
            loop.run_until_complete(self._synthesis_loop())
        except Exception as e:
            print(f"TTS synthesis worker error: {e}")
        finally:
            loop.close()
            self.is_processing = False

    async def _synthesis_loop(self):
        """异步合成循环"""
        while not self.stop_synthesis:
            try:
                # 尝试获取待合成的句子
                sentence = self.pending_sentences.get(timeout=1.0)

                if sentence and not self.stop_synthesis:
                    # 使用锁确保同一时间只有一个句子在合成
                    async with self.synthesis_lock:
                        if not self.stop_synthesis:  # 再次检查，避免在等待锁期间被停止
                            self.current_synthesizing_sentence = sentence
                            print(
                                f"开始合成句子 {self.processed_sentences + 1}: {sentence[:50]}..."
                            )

                            # 执行TTS合成
                            await self._synthesize_sentence(sentence)
                            self.processed_sentences += 1

                            self.current_synthesizing_sentence = None
                            print(
                                f"完成合成句子 {self.processed_sentences}: {sentence[:50]}..."
                            )

            except Empty:
                # 队列为空，继续等待
                continue
            except Exception as e:
                print(f"Error in synthesis loop: {e}")
                # 发生错误时也要清除当前合成状态
                self.current_synthesizing_sentence = None

    async def _synthesize_sentence(self, sentence: str):
        """合成单个句子"""
        try:
            # 定义流式回调函数
            async def sentence_stream_callback(chunk_data):
                if self.stream_callback:
                    # 添加句子信息到chunk数据
                    chunk_data["sentence"] = sentence
                    chunk_data["total_sentences"] = self.total_sentences
                    chunk_data["processed_sentences"] = (
                        self.processed_sentences + 1
                    )  # +1 因为当前句子正在处理
                    chunk_data["current_sentence_index"] = self.processed_sentences + 1
                    await self.stream_callback(chunk_data)

            # 使用统一的TTS会话ID，而不是为每个句子创建新的会话
            # 这样可以更好地控制并发，避免多个会话同时合成
            result = await tts_executor.synthesize_text(
                session_id=self.session_id,  # 使用统一的会话ID
                text=sentence,
                spk_id=self.spk_id,
                stream_callback=sentence_stream_callback,
            )

            if result["status"] != "completed":
                print(f"句子合成失败: {sentence[:50]}... - {result}")

        except Exception as e:
            print(f"Error synthesizing sentence '{sentence[:50]}...': {e}")

    def stop_processing(self):
        """停止合成处理"""
        self.stop_synthesis = True
        self.is_processing = False
        self.current_synthesizing_sentence = None

        # 清空队列
        while not self.pending_sentences.empty():
            try:
                self.pending_sentences.get_nowait()
            except Empty:
                break

    def is_finished(self) -> bool:
        """检查所有待处理的句子是否都已合成完毕"""
        return (
            self.pending_sentences.empty()
            and self.current_synthesizing_sentence is None
        )

    def get_status(self) -> Dict[str, Any]:
        """获取会话状态信息"""
        return {
            "session_id": self.session_id,
            "buffer_length": len(self.text_buffer),
            "pending_sentences": self.pending_sentences.qsize(),
            "total_sentences": self.total_sentences,
            "processed_sentences": self.processed_sentences,
            "is_processing": self.is_processing,
            "current_synthesizing_sentence": (
                self.current_synthesizing_sentence[:50] + "..."
                if self.current_synthesizing_sentence
                and len(self.current_synthesizing_sentence) > 50
                else self.current_synthesizing_sentence
            ),
        }


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

        # 音频数据缓存用于保存WAV文件
        self.audio_data_buffer = []
        self.sample_rate = 16000  # 默认采样率
        self.channels = 1  # 单声道
        self.sample_width = 2  # 16-bit audio (2 bytes per sample)

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

        # 将音频数据添加到缓存中用于保存WAV文件
        self.audio_data_buffer.append(audio_data)

    def save_audio_as_wav(self, filename=None):
        """将收集的音频数据保存为WAV文件"""
        if not self.audio_data_buffer:
            print("No audio data to save")
            return None

        try:
            # 确保saved_audio目录存在
            save_dir = "saved_audio"
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)

            # 生成文件名
            if filename is None:
                timestamp = int(time.time() * 1000)  # 毫秒时间戳
                filename = f"{self.session_id}_{timestamp}.wav"

            filepath = os.path.join(save_dir, filename)

            # 合并所有音频数据
            combined_audio_data = b"".join(self.audio_data_buffer)

            # 保存为WAV文件
            with wave.open(filepath, "wb") as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(self.sample_width)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(combined_audio_data)

            print(f"Audio saved as: {filepath}")
            return filepath

        except Exception as e:
            print(f"Error saving audio as WAV: {e}")
            return None

    def stop_processing(self):
        """停止处理"""
        self.is_processing = False
        if self.web_audio_handler:
            self.web_audio_handler.stop()

        # 在停止处理时保存音频文件
        self.save_audio_as_wav()


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
        # 停止处理并保存音频文件
        asr_sessions[sid].stop_processing()
        del asr_sessions[sid]

    # 清理TTS会话
    tts_executor.remove_session(sid)

    # 清理TTS缓冲会话
    if sid in tts_buffer_sessions:
        tts_buffer_sessions[sid].stop_processing()
        del tts_buffer_sessions[sid]


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
            audio_bytes = None
            if isinstance(data["audio"], bytes):
                audio_bytes = data["audio"]  # ← 无需任何转换！
                asr_sessions[sid].add_audio_data(audio_bytes)

                # 打印音频数据统计信息
                buffer_count = len(asr_sessions[sid].audio_data_buffer)
                total_bytes = sum(
                    len(chunk) for chunk in asr_sessions[sid].audio_data_buffer
                )
                print(
                    f"Session {sid}: Buffer chunks: {buffer_count}, Total bytes: {total_bytes}"
                )
            else:
                print(f"Unsupported audio data format: {type(data['audio'])}")
                return

    except Exception as e:
        print(f"Error processing audio data: {e}")
        await sio.emit(
            "error", {"message": f"Audio processing error: {str(e)}"}, room=sid
        )


@sio.event
async def stop_asr(sid):
    """停止ASR处理"""
    if sid in asr_sessions:
        # 停止处理（这会自动保存音频文件）
        asr_sessions[sid].stop_processing()
        await sio.emit("asr_stopped", {"session_id": sid}, room=sid)


@sio.event
async def save_audio(sid, data=None):
    """手动保存当前会话的音频数据"""
    if sid not in asr_sessions:
        await sio.emit("error", {"message": "ASR session not found"}, room=sid)
        return

    try:
        filename = data.get("filename") if data else None
        filepath = asr_sessions[sid].save_audio_as_wav(filename)

        if filepath:
            await sio.emit(
                "audio_saved",
                {
                    "session_id": sid,
                    "filepath": filepath,
                    "message": f"Audio saved successfully to {filepath}",
                },
                room=sid,
            )
        else:
            await sio.emit("error", {"message": "Failed to save audio file"}, room=sid)

    except Exception as e:
        print(f"Error saving audio: {e}")
        await sio.emit("error", {"message": f"Error saving audio: {str(e)}"}, room=sid)


"""
客户端能传入文本片段，需要在服务端缓冲区进行拼接，分句合成音频

服务端可能存在未满足分句条件的缓存文本，
需要在文本流发送结束后立刻发送停止语音合成，
并且合成所有缓存文本的指令，否则有可能丢失文本。
"""


@sio.event
async def start_tts(sid, data):
    """开始TTS合成"""
    print(f"Starting TTS for session: {sid}")

    try:
        text = data.get("text", "")
        spk_id = data.get("spk_id", 0)
        tts_type = data.get("type", "basic")  # 基础TTS或流式TTS

        if not text:
            await sio.emit("tts_error", {"error": "Text is required"}, room=sid)
            return

        # 定义流式回调函数
        async def stream_callback(chunk_data):
            # 添加类型信息
            chunk_data["type"] = tts_type
            await sio.emit("tts_stream_audio", chunk_data, room=sid)

        # 开始TTS合成
        result = await tts_executor.synthesize_text(
            session_id=sid, text=text, spk_id=spk_id, stream_callback=stream_callback
        )

        if result["status"] == "completed":
            # 添加类型信息到完成事件
            result["type"] = tts_type
            await sio.emit("tts_synthesis_complete", result, room=sid)
        else:
            await sio.emit("tts_error", result, room=sid)

    except Exception as e:
        print(f"TTS error: {e}")
        await sio.emit("tts_error", {"error": str(e)}, room=sid)


@sio.event
async def start_stream_tts(sid, data):
    """开始流式TTS合成（支持缓冲）"""
    print(f"Starting streaming TTS for session: {sid}")

    try:
        spk_id = data.get("spk_id", 0)
        max_buffer_size = data.get("max_buffer_size", 1000)

        # 如果已存在会话，先停止
        if sid in tts_buffer_sessions:
            tts_buffer_sessions[sid].stop_processing()
            del tts_buffer_sessions[sid]

        # 创建新的TTS缓冲会话
        buffer_session = TTSBufferSession(
            session_id=sid, spk_id=spk_id, max_buffer_size=max_buffer_size
        )

        # 定义流式回调函数
        async def stream_callback(chunk_data):
            # 为流式TTS添加类型信息
            chunk_data["type"] = "stream"
            await sio.emit("tts_stream_audio", chunk_data, room=sid)

        buffer_session.set_stream_callback(stream_callback)
        tts_buffer_sessions[sid] = buffer_session

        # 开始后台合成处理
        buffer_session.start_synthesis()

        await sio.emit(
            "stream_tts_started",
            {"session_id": sid, "spk_id": spk_id, "max_buffer_size": max_buffer_size},
            room=sid,
        )

    except Exception as e:
        print(f"Stream TTS start error: {e}")
        await sio.emit("tts_error", {"error": str(e)}, room=sid)


@sio.event
async def stream_text(sid, data):
    """接收流式文本数据"""
    if sid not in tts_buffer_sessions:
        await sio.emit("tts_error", {"error": "Stream TTS session not found"}, room=sid)
        return

    try:
        text = data.get("text", "")

        if not text:
            return

        # 添加文本到缓冲区
        buffer_session = tts_buffer_sessions[sid]
        sentences = buffer_session.add_text(text)

        # 发送状态更新
        status = buffer_session.get_status()
        await sio.emit(
            "tts_buffer_status",
            {"status": status, "new_sentences": len(sentences)},
            room=sid,
        )

    except Exception as e:
        print(f"Stream text error: {e}")
        await sio.emit("tts_error", {"error": str(e)}, room=sid)


@sio.event
async def flush_tts_buffer(sid):
    """清空TTS缓冲区，合成剩余文本，并在完成后发送信号"""
    if sid not in tts_buffer_sessions:
        await sio.emit("tts_error", {"error": "Stream TTS session not found"}, room=sid)
        return

    try:
        buffer_session = tts_buffer_sessions[sid]
        remaining_sentences = buffer_session.flush_buffer()

        # 发送缓冲区清空状态
        status = buffer_session.get_status()
        await sio.emit(
            "tts_buffer_flushed",
            {
                "status": status,
                "remaining_sentences": len(remaining_sentences),
                "sentences": remaining_sentences,
            },
            room=sid,
        )

        # 启动一个后台任务来等待所有句子合成完毕
        asyncio.create_task(_wait_for_synthesis_completion(sid, buffer_session))

    except Exception as e:
        print(f"Flush TTS buffer error: {e}")
        await sio.emit("tts_error", {"error": str(e)}, room=sid)


async def _wait_for_synthesis_completion(sid: str, session: TTSBufferSession):
    """等待指定会话的所有句子合成完成"""
    while not session.is_finished():
        await asyncio.sleep(0.1)

    # 所有句子都已合成完毕，发送完成信号
    print(f"所有句子合成完毕，会话: {sid}")
    await sio.emit("stream_tts_finished", {"session_id": sid}, room=sid)


@sio.event
async def get_tts_status(sid):
    """获取TTS会话状态"""
    try:
        if sid in tts_buffer_sessions:
            status = tts_buffer_sessions[sid].get_status()
            await sio.emit("tts_status", status, room=sid)
        else:
            await sio.emit("tts_status", {"session_id": sid, "exists": False}, room=sid)

    except Exception as e:
        print(f"Get TTS status error: {e}")
        await sio.emit("tts_error", {"error": str(e)}, room=sid)


@sio.event
async def stop_tts(sid):
    """停止TTS合成"""
    print(f"Stopping TTS for session: {sid}")

    # 停止普通TTS会话
    tts_executor.remove_session(sid)

    # 停止流式TTS缓冲会话
    if sid in tts_buffer_sessions:
        tts_buffer_sessions[sid].stop_processing()
        del tts_buffer_sessions[sid]

    await sio.emit("tts_stopped", {"session_id": sid}, room=sid)


if __name__ == "__main__":
    print("Starting Web ASR Server...")
    print(f"Open http://localhost:{WEB_SERVER_CONFIG['port']} in your browser")
    uvicorn.run(
        socket_app,
        host=WEB_SERVER_CONFIG["host"],
        port=WEB_SERVER_CONFIG["port"],
    )
