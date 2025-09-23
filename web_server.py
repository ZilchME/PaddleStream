import asyncio
import base64
import re
import threading

import os
from datetime import datetime


from typing import Optional, List, Callable, Dict, Any
from queue import Queue, Empty
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import socketio
import uvicorn
from audio_hander import WebSocketAudioHandler
from paddlespeech_client import ASROnlineClientExecutor, TTSWebServerExecutor
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

# 全局TTS服务执行器
tts_executor = TTSWebServerExecutor(
    server_ip=TTS_SERVER_CONFIG["default_ip"], port=TTS_SERVER_CONFIG["default_port"]
)

# 全局TTS缓冲会话管理器
tts_buffer_sessions = {}
# 全局变量，存储音频处理器和ASR客户端
asr_sessions = {}
asr_client = ASROnlineClientExecutor()


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


"""
ASR 相关事件处理
"""


@sio.event
async def start_asr(sid):
    """开始ASR处理"""
    print(f"Starting ASR for session: {sid}")
    asr_session = WebSocketAudioHandler(sample_rate=16000, chunk_size=1024)
    asr_sessions[sid] = asr_session

    asr_session.start_processing()
    asyncio.create_task(process_asr_async(sid, asr_sessions[sid]))
    print(f"Started recording for client {sid}")

    await sio.emit("asr_started", {"session_id": sid}, room=sid)


async def process_asr_async(sid, audio_handler):
    """异步处理ASR"""
    try:
        # 定义实时结果回调函数
        def real_time_callback(result, result_type="partial"):
            # 发送实时结果到前端
            async def send_result():
                await sio.emit(
                    "asr_partial_result",
                    {
                        "result": result,
                        "type": result_type,
                        "session_id": sid,
                    },
                    room=sid,
                )

            asyncio.run_coroutine_threadsafe(send_result(), loop)

        # 在线程池中运行阻塞的ASR处理
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: asr_client.process_websocket_audio(
                audio_handler=audio_handler,
                server_ip=ASR_SERVER_CONFIG["default_ip"],
                port=ASR_SERVER_CONFIG["default_port"],
                real_time_callback=real_time_callback,
            ),
        )

        # 发送最终结果到前端
        await sio.emit(
            "asr_result",
            {
                "status": "completed",
                "result": result,
                "session_id": sid,
            },
            room=sid,
        )
        print(f"Final result for {sid}: {result}")

        # # 保存音频文件
        # saved_file = audio_handler.save_audio_to_file()
        # if saved_file:
        #     print(f"Client {sid} 音频已保存: {saved_file}")

    except Exception as e:
        print(f"ASR processing error: {e}")
        await sio.emit(
            "error", {"message": f"ASR processing error: {str(e)}"}, room=sid
        )


@sio.event
async def audio_data(sid, data):
    """处理音频数据"""
    if sid not in asr_sessions:
        await sio.emit("error", {"message": "ASR session not found"}, room=sid)
        return

    try:
        # 从前端接收的是base64编码的音频数据
        if isinstance(data, dict) and "audio" in data:
            # 解码base64音频数据
            audio_bytes = base64.b64decode(data["audio"])
            # 添加到音频处理器
            asr_sessions[sid].add_audio_data(audio_bytes)
        elif isinstance(data, bytes):
            # 直接是字节数据
            asr_sessions[sid].add_audio_data(data)
        else:
            print(f"Unexpected audio data format from {sid}: {type(data)}")

    except Exception as e:
        print(f"Error processing audio data: {e}")
        await sio.emit(
            "error", {"message": f"Audio processing error: {str(e)}"}, room=sid
        )


@sio.event
async def stop_asr(sid):
    """停止ASR处理"""
    if sid in asr_sessions:
        asr_session = asr_sessions[sid]
        asr_session.stop_processing()
        await sio.emit("asr_stopped", {"session_id": sid}, room=sid)

    else:
        await sio.emit("error", {"message": "音频处理器未找到"}, room=sid)


"""
TTS 相关事件处理
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
