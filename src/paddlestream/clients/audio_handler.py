import base64
import json
import time
import asyncio
from pathlib import Path

import numpy as np
import requests
import soundfile
import websockets
import queue

from datetime import datetime

from ..core.logging_utils import get_logger

logger = get_logger("paddlestream.audio")

class TextHttpHandler:
    def __init__(
        self,
        server_ip=None,
        port=None,
        timeout=None,
    ):
        """Text http client request

        Args:
            server_ip (str, optional): the text server ip.
            port (int, optional): the text server port.
        """
        super().__init__()
        self.server_ip = server_ip
        self.port = port
        self.timeout = timeout
        if server_ip is None or port is None:
            self.url = None
        else:
            self.url = (
                "http://" + self.server_ip + ":" + str(self.port) + "/paddlespeech/text"
            )
        logger.info("TextHttpHandler endpoint: %s", self.url)

    def run(self, text):
        """Call the text server to process the specific text

        Args:
            text (str): the text to be processed

        Returns:
            str: punctuation text
        """
        if self.server_ip is None or self.port is None:
            return text
        if self.timeout is None:
            raise ValueError("标点服务请求超时未配置，请设置 PADDLESTREAM_SYNC_HTTP_TIMEOUT_SECONDS")
        request = {
            "text": text,
        }
        try:
            res = requests.post(url=self.url, json=request, timeout=self.timeout)
            response_dict = res.json()
            punc_text = response_dict["result"]["punc_text"]
        except Exception as e:
            logger.error("Call punctuation %s failed: %s", self.url, e)
            punc_text = text

        return punc_text


class WebSocketAudioHandler:
    def __init__(self, sample_rate=16000, chunk_size=1024):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.audio_queue = queue.Queue()
        self.is_receiving = False
        self.audio_data_buffer = []  # 用于保存完整的音频数据

    def add_audio_data(self, audio_data: bytes):
        """从Web端接收音频数据"""
        if self.is_receiving:
            # 将字节数据转换为numpy数组
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            self.audio_queue.put(audio_array.copy())
            # 同时保存到缓冲区用于后续保存文件
            self.audio_data_buffer.append(audio_array.copy())

    def start_processing(self):
        """开始接收音频数据"""
        self.is_receiving = True
        self.audio_data_buffer = []  # 清空缓冲区

    def stop_processing(self):
        """停止接收音频数据"""
        self.is_receiving = False

    def read_audio_stream(self):
        """生成器，返回音频数据流"""
        while self.is_receiving or not self.audio_queue.empty():
            try:
                yield self.audio_queue.get(timeout=0.1)
            except queue.Empty:
                if not self.is_receiving:
                    break
                continue

    def save_audio_to_file(self, filename=None, output_dir="audio_files"):
        """保存接收到的音频缓冲到 WAV 文件。

        Args:
            filename: 文件名或文件名 stem。未提供时自动生成时间戳文件名。
            output_dir: 输出目录。

        Returns:
            保存成功时返回文件路径字符串，否则返回 None。
        """
        if not self.audio_data_buffer:
            logger.warning("没有音频数据可保存")
            return None

        try:
            output_path = _resolve_output_path(filename, output_dir)
            complete_audio = np.concatenate(self.audio_data_buffer).astype(np.int16)
            _write_wav_file(output_path, complete_audio, self.sample_rate)
            logger.info("音频文件已保存: %s", output_path)
            logger.info("音频长度: %.2f 秒", len(complete_audio) / self.sample_rate)
            return str(output_path)
        except Exception as e:
            logger.error("保存音频文件失败: %s", e)
            return None


class ASRServiceNotAvailableError(Exception):
    """ASR 服务不可用异常"""
    pass


class ASRWsAudioHandler:
    def __init__(
        self,
        url=None,
        port=None,
        endpoint=None,
        punc_server_ip=None,
        punc_server_port=None,
        punc_request_timeout=None,
        max_retries=2,
        retry_delay=1.0,
        final_result_timeout=30.0,
    ):
        """PaddleSpeech Online ASR Server Client  audio handler
           Online asr server use the websocket protocol
        Args:
            url (str, optional): the server ip.
            port (int, optional): the server port.
            endpoint(str, optional): to compatiable with python server and c++ server.
            punc_server_ip(str, optional): the punctuation server ip.
            punc_server_port(int, optional): the punctuation port.
            max_retries (int, optional): max connection retry times.
            retry_delay (float, optional): retry delay in seconds.
            final_result_timeout (float, optional): deadline in seconds to receive
                the finished response after sending the end signal.
        """
        self.url = url
        self.port = port
        self.endpoint = endpoint
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.final_result_timeout = final_result_timeout
        if url is None or port is None or endpoint is None:
            self.url = None
        else:
            self.url = "ws://" + self.url + ":" + str(self.port) + endpoint
        self.punc_server = TextHttpHandler(
            punc_server_ip, punc_server_port, timeout=punc_request_timeout
        )
        self.is_server_available = False
        logger.info("ASR endpoint: %s", self.url)

    async def health_check(self) -> bool:
        """Check if the ASR server is reachable by attempting a WebSocket connection.

        Returns:
            bool: True if server is available, False otherwise.
        """
        if self.url is None:
            logger.warning("[ASR Health Check] URL is not configured")
            return False
        try:
            async with websockets.connect(self.url, ping_interval=None, ping_timeout=10):
                self.is_server_available = True
                return True
        except Exception as e:
            self.is_server_available = False
            logger.warning("[ASR Health Check] Server unavailable: %s", e)
            return False

    async def run_websocket_audio(
        self, audio_handler: WebSocketAudioHandler, real_time_callback=None
    ):
        """处理来自WebSocket的音频数据流
        
        包含服务健康检查和重试机制，当 ASR 服务不可用时抛出 ASRServiceNotAvailableError。
        """
        if self.url is None:
            logger.error("[ASR Fallback] No asr server configured, please input valid ip and port")
            raise ASRServiceNotAvailableError("ASR服务未配置，请检查配置文件中的 ASR_SERVER_CONFIG")
        if self.punc_server.server_ip is not None and self.punc_server.port is not None and self.punc_server.timeout is None:
            raise ASRServiceNotAvailableError("标点服务请求超时未配置，请设置 PADDLESTREAM_SYNC_HTTP_TIMEOUT_SECONDS")

        # 预检查服务可用性
        if not await self.health_check():
            raise ASRServiceNotAvailableError(
                f"ASR服务不可用 ({self.url})，请检查服务是否启动"
            )

        # 建立WebSocket连接
        start_time = time.time()
        async with websockets.connect(
            self.url, ping_interval=None, ping_timeout=10
        ) as ws:
            # 发送开始信号
            audio_info = json.dumps(
                {
                    "name": "websocket_audio",
                    "signal": "start",
                    "nbest": 1,
                },
                sort_keys=True,
                indent=4,
                separators=(",", ": "),
            )
            await ws.send(audio_info)
            msg = await ws.recv()
            logger.info("ASR server: %s", msg)

            # 发送音频数据
            logger.info("开始处理WebSocket音频数据...")

            final_message = None
            # 生成器负责排空队列；已取出的最后一块也必须发送。
            # 重复的识别文本不代表静音，结束以上游 finished 或显式停止为准。
            for chunk_data in audio_handler.read_audio_stream():
                # 处理音频数据块
                chunk_data = chunk_data.astype(np.int16)
                await ws.send(chunk_data.tobytes())

                # 非阻塞接收消息
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.1)
                    msg = json.loads(msg)
                    if msg.get("signal") == "finished":
                        final_message = msg
                        audio_handler.stop_processing()
                        break
                    current_result = msg.get("result", "")
                    logger.debug("client receive msg=%s", msg)

                    if real_time_callback and current_result:
                        real_time_callback(current_result, msg.get("type", "partial"))

                except asyncio.TimeoutError:
                    continue

            if final_message is None:
                # 排空音频后发送结束信号，跳过积压的 partial，直到收到 finished。
                audio_info = json.dumps(
                    {
                        "name": "websocket_audio",
                        "signal": "end",
                        "nbest": 1,
                    },
                    sort_keys=True,
                    indent=4,
                    separators=(",", ": "),
                )
                await ws.send(audio_info)
                try:
                    async with asyncio.timeout(self.final_result_timeout):
                        while final_message is None:
                            msg = json.loads(await ws.recv())
                            if msg.get("signal") == "finished":
                                final_message = msg
                            elif real_time_callback and msg.get("result"):
                                real_time_callback(msg["result"], msg.get("type", "partial"))
                except asyncio.TimeoutError as e:
                    raise TimeoutError("等待 ASR finished 响应超时") from e

            msg = final_message
            if not isinstance(msg.get("result"), str):
                raise ValueError("ASR finished 响应缺少有效的 result 字符串")

            # 添加标点
            if self.punc_server and len(msg["result"]) > 0:
                msg["result"] = self.punc_server.run(msg["result"])

            # 计算处理时间
            elapsed_time = time.time() - start_time
            logger.info("elapsed time: %s", elapsed_time)
            logger.info("final result: %s", msg["result"])

            return msg


class TTSWsHandler:
    def __init__(
        self,
        server=None,
        port=None,
        endpoint=None,
        sample_rate_timeout: float = None,
    ):
        """PaddleSpeech Online TTS Server Client  audio handler
           Online tts server use the websocket protocol
        Args:
            server (str, optional): the server ip.
            port (int, optional): the server port.
        """
        self.server = server
        self.port = port
        self.endpoint = endpoint
        self.url = (
            None
            if server is None or port is None or endpoint is None
            else "ws://" + self.server + ":" + str(self.port) + endpoint
        )

        self.sample_rate = None
        self.url_get_sr = None
        if self.url is not None:
            if sample_rate_timeout is None:
                raise ValueError(
                    "TTS 采样率请求超时未配置，请设置 PADDLESTREAM_SYNC_HTTP_TIMEOUT_SECONDS"
                )
            self.url_get_sr = (
                "http://"
                + str(self.server)
                + ":"
                + str(self.port)
                + f"{endpoint}/samplerate"
            )
            try:
                self.sample_rate = requests.get(
                    self.url_get_sr, timeout=sample_rate_timeout
                ).json().get("sample_rate")
            except Exception as e:
                raise RuntimeError(
                    f"Failed to fetch TTS sample rate from {self.url_get_sr}: {e}"
                ) from e
        logger.info("TTS endpoint: %s", self.url)

    async def run(self, text: str, spk_id=0, output: str = None):
        """Send a text to online server

        Args:
            text (str): sentence to be synthesized
            spk_id (int, optional): speaker id. Defaults to 0.
            output (str, optional): client save audio path. Defaults to None.
        """
        if self.url is None:
            raise ValueError("TTS 服务未配置，请设置 PADDLESTREAM_TTS_SERVER_IP 和 PADDLESTREAM_TTS_SERVER_PORT")
        if self.sample_rate is None:
            raise ValueError("TTS 采样率未配置，请检查 TTS 服务或配置参数")

        all_bytes = b""
        receive_time_list = []
        chunk_duration_list = []

        # 1. Send websocket handshake request
        async with websockets.connect(self.url) as ws:
            # 2. Server has already received handshake response, send start request
            start_request = json.dumps({"task": "tts", "signal": "start"})
            await ws.send(start_request)
            msg = await ws.recv()
            logger.debug("client receive msg=%s", msg)
            msg = json.loads(msg)
            session = msg["session"]

            # 3. send speech synthesis request
            # text_base64 = str(base64.b64encode((text).encode('utf-8')), "UTF8")
            params = {
                "text": text,
                "spk_id": spk_id,
            }

            request = json.dumps(params)
            st = time.time()
            await ws.send(request)
            logger.debug("send a message to the server")

            # 4. Process the received response
            message = await ws.recv()
            first_response = time.time() - st
            message = json.loads(message)
            status = message["status"]
            while True:
                # When throw an exception
                if status == -1:
                    # send end request
                    end_request = json.dumps(
                        {"task": "tts", "signal": "end", "session": session}
                    )
                    await ws.send(end_request)
                    break

                # Rerutn last packet normally, no audio information
                elif status == 2:
                    final_response = time.time() - st
                    duration = len(all_bytes) / 2.0 / self.sample_rate

                    if output is not None:
                        save_audio_success = save_audio(
                            all_bytes, output, self.sample_rate
                        )
                    else:
                        save_audio_success = False

                    # send end request
                    end_request = json.dumps(
                        {"task": "tts", "signal": "end", "session": session}
                    )
                    await ws.send(end_request)
                    break

                # Return the audio stream normally
                elif status == 1:
                    receive_time_list.append(time.time())
                    audio = message["audio"]
                    audio = base64.b64decode(audio)  # bytes
                    chunk_duration_list.append(len(audio) / 2.0 / self.sample_rate)
                    all_bytes += audio

                    message = await ws.recv()
                    message = json.loads(message)
                    status = message["status"]

                else:
                    logger.error("infer error, return status is invalid.")

        return (
            first_response,
            final_response,
            duration,
            save_audio_success,
            receive_time_list,
            chunk_duration_list,
        )


def save_audio(bytes_data, audio_path, sample_rate: int = 24000) -> bool:
    """将 PCM16 字节流保存为 pcm 或 wav 文件。

    Args:
        bytes_data: PCM16 little-endian 字节流。
        audio_path: 目标路径，支持 `.pcm` 和 `.wav`。
        sample_rate: wav 保存时使用的采样率。

    Returns:
        保存成功返回 True，否则返回 False。
    """
    try:
        target_path = Path(audio_path).expanduser()
        suffix = target_path.suffix.lower()
        if suffix not in {".pcm", ".wav"}:
            logger.warning("Only supports saved audio format is pcm or wav")
            return False

        target_path.parent.mkdir(parents=True, exist_ok=True)
        if suffix == ".pcm":
            target_path.write_bytes(bytes_data)
        else:
            audio_array = _pcm_bytes_to_int16_array(bytes_data)
            _write_wav_file(target_path, audio_array, sample_rate)
        return True
    except Exception as e:
        logger.error("保存音频文件失败: %s", e)
        return False


def _resolve_output_path(filename, output_dir) -> Path:
    output_dir_path = Path(output_dir).expanduser()
    output_dir_path.mkdir(parents=True, exist_ok=True)

    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"audio_{timestamp}.wav"

    filename_path = Path(filename)
    filename_path = filename_path.with_suffix(".wav")

    if filename_path.is_absolute():
        target_path = filename_path
    else:
        target_path = output_dir_path / filename_path

    target_path.parent.mkdir(parents=True, exist_ok=True)
    return target_path


def _pcm_bytes_to_int16_array(bytes_data: bytes) -> np.ndarray:
    if len(bytes_data) % 2 != 0:
        raise ValueError("PCM16 音频字节长度必须为 2 的倍数")
    return np.frombuffer(bytes_data, dtype=np.int16)


def _write_wav_file(path: Path, audio_array: np.ndarray, sample_rate: int) -> None:
    if sample_rate is None or sample_rate <= 0:
        raise ValueError("采样率必须大于 0")
    soundfile.write(str(path), audio_array.astype(np.int16), sample_rate, subtype="PCM_16")
