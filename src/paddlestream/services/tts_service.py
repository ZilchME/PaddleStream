import asyncio
import re
import threading
from queue import Empty, Queue
from typing import Any, Callable, Dict, List, Optional

from ..core.text_utils import normalize_text


class TTSBufferSession:
    """TTS缓冲会话类，支持流式文本输入和实时语音合成。"""

    def __init__(
        self,
        session_id: str,
        spk_id: int,
        max_buffer_size: int,
        tts_executor,
        logger,
    ):
        self.session_id = session_id
        self.spk_id = spk_id
        self.max_buffer_size = max_buffer_size
        self.tts_executor = tts_executor
        self.logger = logger

        self.text_buffer = ""
        self.pending_sentences = Queue()
        self.sentence_endings = re.compile(r"[。！？；;\!\?\n]+")

        self.is_processing = False
        self.synthesis_thread = None
        self.stop_synthesis = False
        self.stop_accepting_new_text = False

        self.synthesis_lock = None
        self.current_synthesizing_sentence = None

        self.stream_callback: Optional[Callable] = None
        self.total_sentences = 0
        self.processed_sentences = 0

    def set_stream_callback(self, callback: Callable):
        self.stream_callback = callback

    def add_text(self, text: str) -> List[str]:
        if self.stop_accepting_new_text:
            self.logger.info("会话 %s 已停止接受新文本", self.session_id)
            return []

        self.text_buffer += text
        if len(self.text_buffer) > self.max_buffer_size:
            sentences = self._force_split_buffer()
        else:
            sentences = self._extract_sentences()

        filtered_sentences = []
        for sentence in sentences:
            cleaned = normalize_text(sentence)
            if cleaned:
                filtered_sentences.append(cleaned)
                self.pending_sentences.put(cleaned)
                self.total_sentences += 1
                self.logger.info(
                    "[Session %s] 入队待合成句子 [%d/%d]: %s",
                    self.session_id,
                    self.total_sentences,
                    self.max_buffer_size,
                    cleaned[:200],
                )
        return filtered_sentences

    def _extract_sentences(self) -> List[str]:
        sentences = []
        parts = self.sentence_endings.split(self.text_buffer)
        if len(parts) > 1:
            sentences = parts[:-1]
            self.text_buffer = parts[-1]
        return sentences

    def _force_split_buffer(self) -> List[str]:
        sentences = []
        normal_sentences = self._extract_sentences()
        sentences.extend(normal_sentences)

        if len(self.text_buffer) > self.max_buffer_size // 2:
            comma_parts = re.split(r"[，,；;：:]", self.text_buffer)
            if len(comma_parts) > 1:
                sentences.extend(comma_parts[:-1])
                self.text_buffer = comma_parts[-1]
            else:
                chunk_size = self.max_buffer_size // 4
                while len(self.text_buffer) > chunk_size:
                    sentences.append(self.text_buffer[:chunk_size])
                    self.text_buffer = self.text_buffer[chunk_size:]

        return sentences

    def flush_buffer(self) -> List[str]:
        sentences = []
        if self.text_buffer.strip():
            cleaned = normalize_text(self.text_buffer)
            if cleaned:
                sentences.append(cleaned)
                self.pending_sentences.put(cleaned)
                self.total_sentences += 1
                self.logger.info(
                    "[Session %s] flush: 入队剩余文本 [%d/%d]: %s",
                    self.session_id,
                    self.total_sentences,
                    self.max_buffer_size,
                    cleaned[:200],
                )
            self.text_buffer = ""
        return sentences

    def start_synthesis(self):
        if self.is_processing:
            return

        self.is_processing = True
        self.stop_synthesis = False
        self.synthesis_thread = threading.Thread(target=self._synthesis_worker)
        self.synthesis_thread.start()

    def _synthesis_worker(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.synthesis_lock = asyncio.Lock()

        try:
            loop.run_until_complete(self._synthesis_loop())
        except Exception as e:
            self.logger.error("[Session %s] TTS 合成工作线程异常: %s", self.session_id, str(e))
        finally:
            loop.close()
            self.is_processing = False

    async def _synthesis_loop(self):
        while not self.stop_synthesis:
            try:
                sentence = self.pending_sentences.get(timeout=1.0)
                if sentence and not self.stop_synthesis:
                    async with self.synthesis_lock:
                        if not self.stop_synthesis:
                            self.current_synthesizing_sentence = sentence
                            self.logger.info(
                                "[Session %s] 开始合成句子 %d/%d: %s",
                                self.session_id,
                                self.processed_sentences + 1,
                                self.total_sentences,
                                sentence[:200],
                            )
                            await self._synthesize_sentence(sentence)
                            self.processed_sentences += 1
                            self.current_synthesizing_sentence = None
                            self.logger.info(
                                "[Session %s] 完成合成句子 %d/%d: %s",
                                self.session_id,
                                self.processed_sentences,
                                self.total_sentences,
                                sentence[:200],
                            )
            except Empty:
                continue
            except Exception as e:
                self.logger.error("[Session %s] 合成循环异常: %s", self.session_id, str(e))
                self.current_synthesizing_sentence = None

    async def _synthesize_sentence(self, sentence: str):
        try:
            async def sentence_stream_callback(chunk_data):
                if self.stream_callback:
                    chunk_data["sentence"] = sentence
                    chunk_data["total_sentences"] = self.total_sentences
                    chunk_data["processed_sentences"] = self.processed_sentences + 1
                    chunk_data["current_sentence_index"] = self.processed_sentences + 1
                    await self.stream_callback(chunk_data)

            result = await self.tts_executor.synthesize_text(
                session_id=self.session_id,
                text=sentence,
                spk_id=self.spk_id,
                stream_callback=sentence_stream_callback,
            )

            if result["status"] != "completed":
                self.logger.error(
                    "[Session %s] 句子合成失败: %s - %s",
                    self.session_id,
                    sentence[:200],
                    result,
                )
        except Exception as e:
            self.logger.error(
                "[Session %s] 句子合成异常: %s - %s",
                self.session_id,
                sentence[:200],
                str(e),
            )

    def stop_processing(self):
        self.stop_synthesis = True
        self.is_processing = False
        self.current_synthesizing_sentence = None

        while not self.pending_sentences.empty():
            try:
                self.pending_sentences.get_nowait()
            except Empty:
                break

    def is_finished(self) -> bool:
        return self.pending_sentences.empty() and self.current_synthesizing_sentence is None

    def get_status(self) -> Dict[str, Any]:
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


async def _wait_for_synthesis_completion(sid: str, session: TTSBufferSession, sio, logger):
    while not session.is_finished():
        await asyncio.sleep(0.1)
    logger.info("[Session %s] 所有句子合成完毕 (共 %d 句)", sid, session.total_sentences)
    await sio.emit("stream_tts_finished", {"session_id": sid}, room=sid)


async def _graceful_tts_session_cleanup(sid: str, session_manager, logger):
    buffer_session = session_manager.get_tts_buffer_session(sid)
    if not buffer_session:
        return

    max_wait_time = 30
    wait_time = 0
    logger.info("开始清理TTS会话 %s...", sid)

    while (
        buffer_session.current_synthesizing_sentence is not None
        and wait_time < max_wait_time
    ):
        await asyncio.sleep(0.5)
        wait_time += 0.5

    if not buffer_session.pending_sentences.empty():
        logger.info(
            "会话 %s 还有 %d 个待合成句子，继续等待...",
            sid,
            buffer_session.pending_sentences.qsize(),
        )
        while not buffer_session.is_finished() and wait_time < max_wait_time:
            await asyncio.sleep(0.5)
            wait_time += 0.5

    if session_manager.has_tts_buffer_session(sid):
        if wait_time >= max_wait_time:
            logger.warning("TTS会话 %s 清理超时，强制停止", sid)
        else:
            logger.info("TTS会话 %s 清理完成，用时 %.1fs", sid, wait_time)

        existing_session = session_manager.pop_tts_buffer_session(sid)
        if existing_session:
            existing_session.stop_processing()


async def _wait_and_stop_tts_session(sid: str, session_manager, sio, logger):
    buffer_session = session_manager.get_tts_buffer_session(sid)
    if not buffer_session:
        return

    max_wait_time = 60
    wait_time = 0
    logger.info("等待TTS会话 %s 完成合成...", sid)

    while not buffer_session.is_finished() and wait_time < max_wait_time:
        await asyncio.sleep(0.5)
        wait_time += 0.5

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

    if session_manager.has_tts_buffer_session(sid):
        if wait_time >= max_wait_time:
            logger.warning("TTS会话 %s 等待超时，强制停止", sid)
            await sio.emit(
                "tts_force_stopped",
                {"session_id": sid, "message": "等待超时，强制停止"},
                room=sid,
            )
        else:
            logger.info("TTS会话 %s 正常完成，用时 %.1fs", sid, wait_time)

        buffer_session.stop_processing()
        session_manager.pop_tts_buffer_session(sid)
        await sio.emit("tts_stopped", {"session_id": sid}, room=sid)


def register_tts_handlers(sio, session_manager, tts_executor, logger) -> None:
    """注册 TTS 相关 Socket.IO 事件。"""

    @sio.event
    async def start_tts(sid, data):
        logger.info("Starting TTS for session: %s", sid)
        try:
            text = normalize_text(data.get("text", ""))
            spk_id = data.get("spk_id", 0)
            tts_type = data.get("type", "basic")

            if not text:
                await sio.emit("tts_error", {"error": "Text is required after normalization"}, room=sid)
                return

            logger.info("[Session %s] 基础TTS: 开始合成 [%d 字符]: %s", sid, len(text), text[:500])

            async def stream_callback(chunk_data):
                chunk_data["type"] = tts_type
                await sio.emit("tts_stream_audio", chunk_data, room=sid)

            result = await tts_executor.synthesize_text(
                session_id=sid, text=text, spk_id=spk_id, stream_callback=stream_callback
            )

            if result["status"] == "completed":
                result["type"] = tts_type
                await sio.emit("tts_synthesis_complete", result, room=sid)
            else:
                await sio.emit("tts_error", result, room=sid)
        except Exception as e:
            logger.error("TTS error: %s", e)
            await sio.emit("tts_error", {"error": str(e)}, room=sid)

    @sio.event
    async def start_stream_tts(sid, data):
        logger.info("Starting streaming TTS for session: %s", sid)
        try:
            spk_id = data.get("spk_id", 0)
            max_buffer_size = data.get("max_buffer_size", 1000)

            existing_session = session_manager.pop_tts_buffer_session(sid)
            if existing_session:
                existing_session.stop_processing()

            buffer_session = TTSBufferSession(
                session_id=sid,
                spk_id=spk_id,
                max_buffer_size=max_buffer_size,
                tts_executor=tts_executor,
                logger=logger,
            )

            async def stream_callback(chunk_data):
                chunk_data["type"] = "stream"
                await sio.emit("tts_stream_audio", chunk_data, room=sid)

            buffer_session.set_stream_callback(stream_callback)
            session_manager.set_tts_buffer_session(sid, buffer_session)
            buffer_session.start_synthesis()

            await sio.emit(
                "stream_tts_started",
                {"session_id": sid, "spk_id": spk_id, "max_buffer_size": max_buffer_size},
                room=sid,
            )
        except Exception as e:
            logger.error("Stream TTS start error: %s", e)
            await sio.emit("tts_error", {"error": str(e)}, room=sid)

    @sio.event
    async def stream_text(sid, data):
        buffer_session = session_manager.get_tts_buffer_session(sid)
        if not buffer_session:
            await sio.emit("tts_error", {"error": "Stream TTS session not found"}, room=sid)
            return

        try:
            text = data.get("text", "")
            if not text:
                return

            sentences = buffer_session.add_text(text)
            status = buffer_session.get_status()
            await sio.emit(
                "tts_buffer_status",
                {"status": status, "new_sentences": len(sentences)},
                room=sid,
            )
        except Exception as e:
            logger.error("Stream text error: %s", e)
            await sio.emit("tts_error", {"error": str(e)}, room=sid)

    @sio.event
    async def flush_tts_buffer(sid):
        logger.info("[Session %s] flush_tts_buffer 被调用", sid)
        buffer_session = session_manager.get_tts_buffer_session(sid)
        if not buffer_session:
            await sio.emit("tts_error", {"error": "Stream TTS session not found"}, room=sid)
            return

        try:
            remaining_sentences = buffer_session.flush_buffer()
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
            asyncio.create_task(_wait_for_synthesis_completion(sid, buffer_session, sio, logger))
        except Exception as e:
            logger.error("Flush TTS buffer error: %s", e)
            await sio.emit("tts_error", {"error": str(e)}, room=sid)

    @sio.event
    async def get_tts_status(sid):
        try:
            buffer_session = session_manager.get_tts_buffer_session(sid)
            if buffer_session:
                status = buffer_session.get_status()
                await sio.emit("tts_status", status, room=sid)
            else:
                await sio.emit("tts_status", {"session_id": sid, "exists": False}, room=sid)
        except Exception as e:
            logger.error("Get TTS status error: %s", e)
            await sio.emit("tts_error", {"error": str(e)}, room=sid)

    @sio.event
    async def stop_tts(sid):
        logger.info("Stopping TTS for session: %s", sid)
        tts_executor.remove_session(sid)

        buffer_session = session_manager.get_tts_buffer_session(sid)
        if buffer_session:
            buffer_session.stop_accepting_new_text = True

            if (
                buffer_session.current_synthesizing_sentence is not None
                or not buffer_session.pending_sentences.empty()
            ):
                await sio.emit(
                    "tts_graceful_stop",
                    {
                        "session_id": sid,
                        "message": "等待当前合成完成...",
                        "pending_sentences": buffer_session.pending_sentences.qsize(),
                    },
                    room=sid,
                )
                asyncio.create_task(_wait_and_stop_tts_session(sid, session_manager, sio, logger))
            else:
                buffer_session.stop_processing()
                session_manager.pop_tts_buffer_session(sid)
                await sio.emit("tts_stopped", {"session_id": sid}, room=sid)
        else:
            await sio.emit("tts_stopped", {"session_id": sid}, room=sid)
