import asyncio
import base64
import re
import threading
import json
import time
import http.client
import codecs
from urllib.parse import urlparse


from typing import Optional, List, Callable, Dict, Any
from queue import Queue, Empty
from fastapi import FastAPI, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import socketio
from audio_hander import WebSocketAudioHandler, TextHttpHandler
from paddlespeech_client import ASROnlineClientExecutor, TTSWebServerExecutor
from config import (
    ASR_SERVER_CONFIG,
    TTS_SERVER_CONFIG,
    WEB_SERVER_CONFIG,
    SOCKETIO_CONFIG,
    SOCKETIO_PATH,
    LLM_API_CONFIG,
)

# 尝试读取标点服务配置，若不存在则使用默认值
try:
    from config import PUNC_SERVER_CONFIG  # type: ignore
except Exception:
    PUNC_SERVER_CONFIG = {"default_ip": None, "default_port": None}

# 创建 FastAPI 应用
app = FastAPI()

# 启用 CORS（与 Socket.IO 保持一致的跨域来源设置）
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


# 全局TTS服务执行器
tts_executor = TTSWebServerExecutor(
    server_ip=TTS_SERVER_CONFIG["default_ip"], port=TTS_SERVER_CONFIG["default_port"]
)

# 全局标点服务客户端
punc_client = TextHttpHandler(
    server_ip=PUNC_SERVER_CONFIG.get("default_ip"),
    port=PUNC_SERVER_CONFIG.get("default_port"),
)


"""
文本标点相关 HTTP 接口
"""


@app.post("/paddlespeech/text/punctuate")
async def punctuate_text(body: Dict[str, Any] = Body(...)):
    """为输入文本添加标点。

    Request JSON:
    {"text": "待添加标点的文本"}

    Response JSON:
    {"result": {"punc_text": "带标点文本"}}
    """
    text = (body or {}).get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="'text' 字段不能为空")

    loop = asyncio.get_running_loop()
    try:
        punc_text = await loop.run_in_executor(None, lambda: punc_client.run(text))
    except Exception as e:
        # 发生异常时，回退为原文本并返回提示
        punc_text = text
        return {"result": {"punc_text": punc_text}, "warning": str(e)}

    return {"result": {"punc_text": punc_text}}


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
        self.sentence_endings = re.compile(r"[。！？；;\!\?\n]+")

        # 合成状态
        self.is_processing = False
        self.synthesis_thread = None
        self.stop_synthesis = False
        self.stop_accepting_new_text = False  # 新增：停止接受新文本标志

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
        # 如果已停止接受新文本，直接返回空列表
        if self.stop_accepting_new_text:
            print(f"会话 {self.session_id} 已停止接受新文本")
            return []

        self.text_buffer += text

        # 检查缓冲区大小
        if len(self.text_buffer) > self.max_buffer_size:
            # 如果缓冲区过大，强制分句（防止内存溢出）
            sentences = self._force_split_buffer()
        else:
            # 正常分句处理
            sentences = self._extract_sentences()

        # 将提取的句子加入待合成队列，并移除英文字母以及部分特殊字符
        
        filtered_sentences = []
        pattern = re.compile(r"[a-zA-Z_\"'`<>《》【】\[\]{}@#$^&*]+")
        for sentence in sentences:
            # 先移除指定字符
            cleaned = pattern.sub("", sentence).strip()
            # 将正斜杠替换为空格
            if "/" in cleaned:
                cleaned = cleaned.replace("/", " ")
            # 规范化：将形如 123,456 或 12,345,678 的大数字中的逗号去除，不影响其它逗号
            cleaned = re.sub(r"\b(\d{1,3}(?:,\d{3})+)\b", lambda m: m.group(1).replace(",", ""), cleaned)
            if cleaned:
                filtered_sentences.append(cleaned)
                self.pending_sentences.put(cleaned)
                self.total_sentences += 1

        return filtered_sentences

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
            comma_parts = re.split(r"[，,；;：:]", self.text_buffer)
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
                                f"开始合成句子 {self.processed_sentences + 1}: {sentence[:100]}..."
                            )

                            # 执行TTS合成
                            await self._synthesize_sentence(sentence)
                            self.processed_sentences += 1

                            self.current_synthesizing_sentence = None
                            print(
                                f"完成合成句子 {self.processed_sentences}: {sentence[:100]}..."
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


@sio.event
async def disconnect(sid):
    """客户端断开连接"""
    print(f"Client disconnected: {sid}")

    # 清理ASR会话
    if sid in asr_sessions:
        # 停止处理并保存音频文件
        asr_sessions[sid].stop_processing()
        del asr_sessions[sid]

    # 清理TTS会话 - 允许当前合成完成
    if sid in tts_buffer_sessions:
        buffer_session = tts_buffer_sessions[sid]
        if buffer_session.is_processing:
            print(f"等待TTS会话 {sid} 的剩余合成完成...")
            # 停止接受新文本，但等待当前合成完成
            buffer_session.stop_accepting_new_text = True
            # 创建异步任务等待完成，避免阻塞disconnect
            asyncio.create_task(_graceful_tts_session_cleanup(sid))
        else:
            # 没有正在进行的合成，直接清理
            buffer_session.stop_processing()
            del tts_buffer_sessions[sid]

    # 清理普通TTS会话
    tts_executor.remove_session(sid)


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
                punc_server_ip=PUNC_SERVER_CONFIG.get("default_ip"),
                punc_server_port=PUNC_SERVER_CONFIG.get("default_port"),
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


async def _graceful_tts_session_cleanup(sid: str):
    """优雅地清理TTS会话 - 等待当前合成完成"""
    if sid not in tts_buffer_sessions:
        return

    buffer_session = tts_buffer_sessions[sid]
    max_wait_time = 30  # 最多等待30秒
    wait_time = 0

    print(f"开始优雅清理TTS会话 {sid}...")

    # 等待当前正在合成的句子完成
    while (
        buffer_session.current_synthesizing_sentence is not None
        and wait_time < max_wait_time
    ):
        await asyncio.sleep(0.5)
        wait_time += 0.5

    # 检查是否还有未处理的句子
    if not buffer_session.pending_sentences.empty():
        print(
            f"会话 {sid} 还有 {buffer_session.pending_sentences.qsize()} 个待合成句子，继续等待..."
        )

        # 等待所有句子完成
        while not buffer_session.is_finished() and wait_time < max_wait_time:
            await asyncio.sleep(0.5)
            wait_time += 0.5

    # 清理会话
    if sid in tts_buffer_sessions:
        if wait_time >= max_wait_time:
            print(f"TTS会话 {sid} 清理超时，强制停止")
        else:
            print(f"TTS会话 {sid} 清理完成，用时 {wait_time:.1f}s")

        tts_buffer_sessions[sid].stop_processing()
        del tts_buffer_sessions[sid]


async def _wait_and_stop_tts_session(sid: str):
    """等待TTS会话完成合成后停止"""
    if sid not in tts_buffer_sessions:
        return

    buffer_session = tts_buffer_sessions[sid]
    max_wait_time = 60  # 最多等待60秒
    wait_time = 0

    print(f"等待TTS会话 {sid} 完成合成...")

    # 等待所有句子合成完毕
    while not buffer_session.is_finished() and wait_time < max_wait_time:
        await asyncio.sleep(0.5)
        wait_time += 0.5

        # 每5秒发送一次状态更新
        if wait_time % 5.0 == 0:
            status = buffer_session.get_status()
            await sio.emit(
                "tts_stop_progress",
                {
                    "session_id": sid,
                    "pending_sentences": status["pending_sentences"],
                    "processed_sentences": status["processed_sentences"],
                    "current_sentence": status.get("current_synthesizing_sentence"),
                },
                room=sid,
            )

    # 停止会话
    if sid in tts_buffer_sessions:
        if wait_time >= max_wait_time:
            print(f"TTS会话 {sid} 等待超时，强制停止")
            await sio.emit(
                "tts_force_stopped",
                {"session_id": sid, "message": "等待超时，强制停止"},
                room=sid,
            )
        else:
            print(f"TTS会话 {sid} 正常完成，用时 {wait_time:.1f}s")

        buffer_session.stop_processing()
        del tts_buffer_sessions[sid]
        await sio.emit("tts_stopped", {"session_id": sid}, room=sid)


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

    # 停止流式TTS缓冲会话 - 支持graceful shutdown
    if sid in tts_buffer_sessions:
        buffer_session = tts_buffer_sessions[sid]

        # 停止接受新文本
        buffer_session.stop_accepting_new_text = True

        # 检查是否有正在进行的合成
        if (
            buffer_session.current_synthesizing_sentence is not None
            or not buffer_session.pending_sentences.empty()
        ):
            # 通知客户端正在等待合成完成
            await sio.emit(
                "tts_graceful_stop",
                {
                    "session_id": sid,
                    "message": "等待当前合成完成...",
                    "pending_sentences": buffer_session.pending_sentences.qsize(),
                },
                room=sid,
            )

            # 创建异步任务等待完成
            asyncio.create_task(_wait_and_stop_tts_session(sid))
        else:
            # 没有进行中的合成，直接停止
            buffer_session.stop_processing()
            del tts_buffer_sessions[sid]
            await sio.emit("tts_stopped", {"session_id": sid}, room=sid)
    else:
        await sio.emit("tts_stopped", {"session_id": sid}, room=sid)


"""
LLM SSE 流式处理相关事件
"""


@sio.event
async def send_llm_message(sid, data):
    """
    接收前端消息,通过SSE方式请求LLM API,并通过WebSocket实时转发响应内容

    Args:
        sid: Socket.IO 会话ID
        data: 包含以下字段的字典:
            - input_text: 用户输入的文本
            - session_id: LLM会话ID (可选)
            - llm_api_url: LLM API地址 (可选,默认使用配置文件中的地址)
    """
    print(f"收到LLM消息请求: {sid}")

    try:
        input_text = data.get("input_text", "")
        llm_session_id = data.get("session_id", sid)  # 默认使用socket sid

        if not input_text:
            await sio.emit("llm_error", {"error": "输入文本不能为空"}, room=sid)
            return

        # 安全获取 LLM API URL（兼容 LLM_API_CONFIG 为空或缺键的情况）
        cfg_url = None
        try:
            if isinstance(LLM_API_CONFIG, dict):
                cfg_url = LLM_API_CONFIG.get("url")
        except Exception:
            cfg_url = None

        llm_api_url = data.get("llm_api_url") or cfg_url

        if not llm_api_url:
            await sio.emit(
                "llm_error",
                {
                    "error": "未配置LLM API地址，请在config.py设置 LLM_API_CONFIG['url'] 或在请求中传入 llm_api_url",
                    "session_id": llm_session_id,
                },
                room=sid,
            )
            return
        # 通知前端开始处理
        await sio.emit("llm_stream_start", {"session_id": llm_session_id}, room=sid)

        # 异步处理SSE流式响应
        await _process_llm_sse_stream(
            sid=sid,
            llm_api_url=llm_api_url,
            input_text=input_text,
            llm_session_id=llm_session_id,
        )

    except Exception as e:
        print(f"LLM消息处理错误: {e}")
        await sio.emit("llm_error", {"error": str(e)}, room=sid)


async def _process_llm_sse_stream(
    sid: str, llm_api_url: str, input_text: str, llm_session_id: str
):
    """
    处理LLM的SSE流式响应,模拟前端的处理逻辑

    Args:
        sid: Socket.IO 会话ID
        llm_api_url: LLM API地址
        input_text: 用户输入文本
        llm_session_id: LLM会话ID
    """
    try:
        # 构造请求数据
        request_data = {
            "input": {"human_input": input_text},
            "config": {
                "configurable": {
                    "session_id": llm_session_id,
                }
            },
        }

        # 在后台线程中执行阻塞的HTTP请求与SSE解析，避免阻塞事件循环
        loop = asyncio.get_running_loop()

        def on_content(content: str):
            # 在线程中回调，将消息安全地投递到事件循环中
            asyncio.run_coroutine_threadsafe(
                sio.emit(
                    "llm_stream_content",
                    {"content": content, "session_id": llm_session_id},
                    room=sid,
                ),
                loop,
            )
            # 按配置添加极短延迟，帮助前端平滑接收
            delay = 0
            if delay > 0:
                time.sleep(delay)

        def worker():
            _blocking_sse_post_and_parse(
                llm_api_url=llm_api_url,
                request_json=request_data,
                on_content=on_content,
            )

        # 等待线程完成
        await asyncio.to_thread(worker)

        # 发送流式传输完成信号
        await sio.emit("llm_stream_complete", {"session_id": llm_session_id}, room=sid)
        print(f"LLM流式响应处理完成: {sid}")

    except Exception as e:
        print(f"LLM SSE流处理错误: {e}")
        await sio.emit(
            "llm_error", {"error": str(e), "session_id": llm_session_id}, room=sid
        )


def _blocking_sse_post_and_parse(
    llm_api_url: str,
    request_json: dict,
    on_content: "Callable[[str], None]",
    read_chunk_size: int = 1024,
    timeout: int = 600,
):
    """
    使用标准库发起POST请求并手动解析SSE流，解析到content即调用 on_content。

    注意：该函数为阻塞式，应放在线程中运行。
    """
    parsed = urlparse(llm_api_url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    port = parsed.port
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    if not host:
        raise ValueError(f"无效的LLM_API_URL: {llm_api_url}")

    # 选择连接类型
    if scheme == "https":
        conn = http.client.HTTPSConnection(host, port=port, timeout=timeout)
    elif scheme == "http":
        conn = http.client.HTTPConnection(host, port=port, timeout=timeout)
    else:
        raise ValueError(f"不支持的协议: {scheme}")

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }

    body = json.dumps(request_json).encode("utf-8")

    # 发起请求
    conn.request("POST", path, body=body, headers=headers)
    resp = conn.getresponse()

    if resp.status != 200:
        error_text = resp.read().decode("utf-8", errors="ignore")
        conn.close()
        raise RuntimeError(f"LLM API请求失败: {resp.status} - {error_text}")

    # 增量解码器，避免UTF-8边界问题
    decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""

    try:
        while True:
            chunk = resp.read(read_chunk_size)
            if not chunk:
                break

            buffer += decoder.decode(chunk, final=False)

            # 兼容 \n\n 或 \r\n\r\n 的块分隔
            event_blocks = re.split(r"(?:\r?\n){2}", buffer)

            if len(event_blocks) > 1:
                # 处理完整块（保留最后一个作为不完整缓存）
                for block in event_blocks[:-1]:
                    block = block.strip()
                    if not block:
                        continue
                    _process_sse_block_sync(block, on_content)

                buffer = event_blocks[-1]

        # 处理剩余数据
        tail = decoder.decode(b"", final=True)
        if tail:
            buffer += tail
        if buffer.strip():
            _process_sse_block_sync(buffer.strip(), on_content)
    finally:
        conn.close()


def _process_sse_block_sync(block: str, on_content: "Callable[[str], None]"):
    """同步处理单个SSE事件块，提取 data: 行中的JSON并回调 content。"""
    lines = block.splitlines()
    # print(f"处理SSE块: {block}...")
    for line in lines:
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue
        json_str = re.sub(r"^data:\s*", "", line)
        if not json_str:
            continue
        # 跳过类似 [DONE]
        if json_str.strip() == "[DONE]":
            continue
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            continue
        content = data.get("content")
        if content:
            # print(f"解析到内容: {content[:50]}...")
            on_content(content)
