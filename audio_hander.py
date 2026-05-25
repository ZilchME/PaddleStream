import base64
import json
import logging
import threading
import time
import asyncio

import numpy as np
import requests
import soundfile
import websockets
import queue
import os
import wave

from datetime import datetime


class TextHttpHandler:
    def __init__(self, server_ip="127.0.0.1", port=8090):
        """Text http client request

        Args:
            server_ip (str, optional): the text server ip. Defaults to "127.0.0.1".
            port (int, optional): the text server port. Defaults to 8090.
        """
        super().__init__()
        self.server_ip = server_ip
        self.port = port
        if server_ip is None or port is None:
            self.url = None
        else:
            self.url = (
                "http://" + self.server_ip + ":" + str(self.port) + "/paddlespeech/text"
            )
        print(f"endpoint: {self.url}")

    def run(self, text):
        """Call the text server to process the specific text

        Args:
            text (str): the text to be processed

        Returns:
            str: punctuation text
        """
        if self.server_ip is None or self.port is None:
            return text
        request = {
            "text": text,
        }
        try:
            res = requests.post(url=self.url, data=json.dumps(request))
            response_dict = res.json()
            punc_text = response_dict["result"]["punc_text"]
        except Exception as e:
            print(f"Call punctuation {self.url} occurs error")
            print(e)
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
        """保存音频数据到文件"""
        if not self.audio_data_buffer:
            print("没有音频数据可保存")
            return None

        # 创建输出目录
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # 生成文件名
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"audio_{timestamp}.wav"

        # 确保文件名以.wav结尾
        if not filename.endswith(".wav"):
            filename += ".wav"

        filepath = os.path.join(output_dir, filename)

        try:
            # 合并所有音频数据
            complete_audio = np.concatenate(self.audio_data_buffer)

            # 保存为WAV文件
            soundfile.write(
                filepath, complete_audio, self.sample_rate, subtype="PCM_16"
            )

            print(f"音频文件已保存: {filepath}")
            print(f"音频长度: {len(complete_audio) / self.sample_rate:.2f} 秒")
            return filepath

        except Exception as e:
            print(f"保存音频文件失败: {e}")
            return None


class ASRServiceNotAvailableError(Exception):
    """ASR 服务不可用异常"""
    pass


class ASRWsAudioHandler:
    def __init__(
        self,
        url=None,
        port=None,
        endpoint="/paddlespeech/asr/streaming",
        punc_server_ip=None,
        punc_server_port=None,
        max_retries=2,
        retry_delay=1.0,
    ):
        """PaddleSpeech Online ASR Server Client  audio handler
           Online asr server use the websocket protocol
        Args:
            url (str, optional): the server ip. Defaults to None.
            port (int, optional): the server port. Defaults to None.
            endpoint(str, optional): to compatiable with python server and c++ server.
            punc_server_ip(str, optional): the punctuation server ip. Defaults to None.
            punc_server_port(int, optional): the punctuation port. Defaults to None
            max_retries (int, optional): max connection retry times. Defaults to 2.
            retry_delay (float, optional): retry delay in seconds. Defaults to 1.0.
        """
        self.url = url
        self.port = port
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        if url is None or port is None or endpoint is None:
            self.url = None
        else:
            self.url = "ws://" + self.url + ":" + str(self.port) + endpoint
        self.punc_server = TextHttpHandler(punc_server_ip, punc_server_port)
        self.is_server_available = False
        print(f"endpoint: {self.url}")

    async def health_check(self) -> bool:
        """Check if the ASR server is reachable by attempting a WebSocket connection.

        Returns:
            bool: True if server is available, False otherwise.
        """
        if self.url is None:
            print("[ASR Health Check] URL is not configured")
            return False
        try:
            async with websockets.connect(self.url, ping_interval=None, ping_timeout=10):
                self.is_server_available = True
                return True
        except Exception as e:
            self.is_server_available = False
            print(f"[ASR Health Check] Server unavailable: {e}")
            return False

    async def run_websocket_audio(
        self, audio_handler: WebSocketAudioHandler, real_time_callback=None
    ):
        """处理来自WebSocket的音频数据流
        
        包含服务健康检查和重试机制，当 ASR 服务不可用时抛出 ASRServiceNotAvailableError。
        """
        if self.url is None:
            print("[ASR Fallback] No asr server configured, please input valid ip and port")
            raise ASRServiceNotAvailableError("ASR服务未配置，请检查配置文件中的 ASR_SERVER_CONFIG")

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
            print(f"server: {msg}")

            # 发送音频数据
            print("开始处理WebSocket音频数据...")

            # 用于检测静音的变量
            last_result = None
            last_result_time = None
            silence_timeout = 3  # 3秒

            for chunk_data in audio_handler.read_audio_stream():
                if not audio_handler.is_receiving and audio_handler.audio_queue.empty():
                    break

                # 处理音频数据块
                chunk_data = chunk_data.astype(np.int16)
                await ws.send(chunk_data.tobytes())

                # 非阻塞接收消息
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.1)
                    msg = json.loads(msg)
                    current_result = msg.get("result", "")
                    print("client receive msg={}".format(msg))

                    if real_time_callback and current_result:
                        real_time_callback(current_result, msg.get("type", "partial"))

                    # 检查结果是否与上次相同
                    if current_result and current_result == last_result:
                        if last_result_time is None:
                            last_result_time = time.time()
                        elif time.time() - last_result_time >= silence_timeout:
                            print(
                                f"No speech detected for {silence_timeout} seconds, closing connection."
                            )
                            break
                    else:
                        last_result = current_result
                        last_result_time = None

                except asyncio.TimeoutError:
                    continue

            # 发送结束信号
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
            msg = await ws.recv()
            msg = json.loads(msg)

            # 添加标点
            if self.punc_server and len(msg["result"]) > 0:
                msg["result"] = self.punc_server.run(msg["result"])

            # 计算处理时间
            elapsed_time = time.time() - start_time
            print(f"elapsed time: {elapsed_time}")
            print(f"final result: {msg['result']}")

            return msg


class TTSWsHandler:
    def __init__(self, server="127.0.0.1", port=8092, play: bool = False):
        """PaddleSpeech Online TTS Server Client  audio handler
           Online tts server use the websocket protocol
        Args:
            server (str, optional): the server ip. Defaults to "127.0.0.1".
            port (int, optional): the server port. Defaults to 8092.
            play (bool, optional): whether to play audio. Defaults False
        """
        self.server = server
        self.port = port
        self.url = (
            "ws://" + self.server + ":" + str(self.port) + "/paddlespeech/tts/streaming"
        )
        self.play = play

        # get model sample rate
        self.url_get_sr = (
            "http://"
            + str(self.server)
            + ":"
            + str(self.port)
            + "/paddlespeech/tts/streaming/samplerate"
        )
        self.sample_rate = requests.get(self.url_get_sr).json()["sample_rate"]

        if self.play:
            import pyaudio

            self.buffer = b""
            self.p = pyaudio.PyAudio()
            self.stream = self.p.open(
                format=self.p.get_format_from_width(2),
                channels=1,
                rate=self.sample_rate,
                output=True,
            )
            self.mutex = threading.Lock()
            self.start_play = True
            self.t = threading.Thread(target=self.play_audio)
            self.max_fail = 50
        print(f"endpoint: {self.url}")

    def play_audio(self):
        while True:
            if not self.buffer:
                self.max_fail -= 1
                time.sleep(0.05)
                if self.max_fail < 0:
                    break
            self.mutex.acquire()
            self.stream.write(self.buffer)
            self.buffer = b""
            self.mutex.release()

    async def run(self, text: str, spk_id=0, output: str = None):
        """Send a text to online server

        Args:
            text (str): sentence to be synthesized
            spk_id (int, optional): speaker id. Defaults to 0.
            output (str, optional): client save audio path. Defaults to None.
        """
        all_bytes = b""
        receive_time_list = []
        chunk_duration_list = []

        # 1. Send websocket handshake request
        async with websockets.connect(self.url) as ws:
            # 2. Server has already received handshake response, send start request
            start_request = json.dumps({"task": "tts", "signal": "start"})
            await ws.send(start_request)
            msg = await ws.recv()
            print(f"client receive msg={msg}")
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
            logging.debug("send a message to the server")

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
                    if self.play:
                        self.mutex.acquire()
                        self.buffer += audio
                        self.mutex.release()
                        if self.start_play:
                            self.t.start()
                            self.start_play = False

                    message = await ws.recv()
                    message = json.loads(message)
                    status = message["status"]

                else:
                    print("infer error, return status is invalid.")

            if self.play:
                self.t.join()
                self.stream.stop_stream()
                self.stream.close()
                self.p.terminate()

        return (
            first_response,
            final_response,
            duration,
            save_audio_success,
            receive_time_list,
            chunk_duration_list,
        )


def save_audio(bytes_data, audio_path, sample_rate: int = 24000) -> bool:
    """save byte to audio file.

    Args:
        bytes_data (bytes): audio samples, bytes format
        audio_path (str): save audio path
        sample_rate (int, optional): audio sample rate. Defaults to 24000.

    Returns:
        bool: Whether the audio was saved successfully
    """

    if audio_path.endswith("pcm"):
        with open(audio_path, "wb") as f:
            f.write(bytes_data)
    elif audio_path.endswith("wav"):
        with open("./tmp.pcm", "wb") as f:
            f.write(bytes_data)
        pcm2wav("./tmp.pcm", audio_path, channels=1, bits=16, sample_rate=sample_rate)
        os.remove("./tmp.pcm")
    else:
        print("Only supports saved audio format is pcm or wav")
        return False

    return True


def pcm2wav(pcm_file, wav_file, channels=1, bits=16, sample_rate=16000):
    """Save the pcm file as a wav file

    Args:
        pcm_file (str): pcm file path
        wav_file (str): wav file save path
        channels (int, optional): audio channel. Defaults to 1.
        bits (int, optional): Bit depth. Defaults to 16.
        sample_rate (int, optional): sample rate. Defaults to 16000.
    """
    pcmf = open(pcm_file, "rb")
    pcmdata = pcmf.read()
    pcmf.close()

    if bits % 8 != 0:
        print("bits % 8 must == 0. now bits:" + str(bits))

    wavfile = wave.open(wav_file, "wb")
    wavfile.setnchannels(channels)
    wavfile.setsampwidth(bits // 8)
    wavfile.setframerate(sample_rate)
    wavfile.writeframes(pcmdata)
    wavfile.close()
