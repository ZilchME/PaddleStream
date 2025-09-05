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
import pyaudio
import queue
from collections import deque


class MicrophoneHandler:
    def __init__(self, sample_rate=16000, chunk_size=1024):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.audio_format = pyaudio.paInt16
        self.channels = 1
        self.is_recording = False
        self.audio_queue = queue.Queue()
        self.audio = pyaudio.PyAudio()

    def _callback(self, in_data, frame_count, time_info, status):
        if self.is_recording:
            audio_data = np.frombuffer(in_data, dtype=np.int16)
            self.audio_queue.put(audio_data.copy())
        return (in_data, pyaudio.paContinue)

    def start(self):
        self.is_recording = True
        self.stream = self.audio.open(
            format=self.audio_format,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size,
            stream_callback=self._callback,
        )
        self.stream.start_stream()

    def stop(self):
        self.is_recording = False
        if hasattr(self, "stream") and self.stream.is_active():
            self.stream.stop_stream()
            self.stream.close()
        self.audio.terminate()

    def read_microphone(self):
        while self.is_recording or not self.audio_queue.empty():
            try:
                yield self.audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue


class WebAudioHandler:
    """处理来自Web前端的音频流"""
    def __init__(self, sample_rate=16000, chunk_size=1024):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.audio_queue = queue.Queue()
        self.is_active = False
        self.buffer = deque()
        self.lock = threading.Lock()

    def add_audio_data(self, audio_data):
        """接收来自前端的音频数据"""
        with self.lock:
            if isinstance(audio_data, bytes):
                # 如果是字节数据，转换为numpy数组
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
            elif isinstance(audio_data, (list, np.ndarray)):
                # 如果是数组，确保是正确的数据类型
                audio_array = np.array(audio_data, dtype=np.int16)
            else:
                print(f"Unsupported audio data type: {type(audio_data)}")
                return
            
            self.buffer.extend(audio_array)
            
            # 当缓冲区有足够数据时，放入队列
            while len(self.buffer) >= self.chunk_size:
                chunk = np.array([self.buffer.popleft() for _ in range(self.chunk_size)])
                self.audio_queue.put(chunk)

    def start(self):
        """开始处理音频"""
        self.is_active = True

    def stop(self):
        """停止处理音频"""
        self.is_active = False
        # 处理剩余的缓冲区数据
        with self.lock:
            if len(self.buffer) > 0:
                remaining_data = np.array(list(self.buffer))
                self.audio_queue.put(remaining_data)
                self.buffer.clear()

    def read_audio_stream(self):
        """生成器，返回音频数据块"""
        while self.is_active or not self.audio_queue.empty():
            try:
                yield self.audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue


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


class ASRWsAudioHandler:
    def __init__(
        self,
        url=None,
        port=None,
        endpoint="/paddlespeech/asr/streaming",
        punc_server_ip=None,
        punc_server_port=None,
    ):
        """PaddleSpeech Online ASR Server Client  audio handler
           Online asr server use the websocket protocol
        Args:
            url (str, optional): the server ip. Defaults to None.
            port (int, optional): the server port. Defaults to None.
            endpoint(str, optional): to compatiable with python server and c++ server.
            punc_server_ip(str, optional): the punctuation server ip. Defaults to None.
            punc_server_port(int, optional): the punctuation port. Defaults to None
        """
        self.url = url
        self.port = port
        if url is None or port is None or endpoint is None:
            self.url = None
        else:
            self.url = "ws://" + self.url + ":" + str(self.port) + endpoint
        self.punc_server = TextHttpHandler(punc_server_ip, punc_server_port)
        print(f"endpoint: {self.url}")


    def create_web_audio_handler(self):
        """创建Web音频处理器"""
        return WebAudioHandler(sample_rate=16000)
    

    async def run_web_audio(self, web_audio_handler, real_time_callback=None):
        """处理来自Web的音频流
        
        Args:
            web_audio_handler: Web音频处理器
            real_time_callback: 实时结果回调函数，用于发送中间识别结果
        """
        if self.url is None:
            print("No asr server, please input valid ip and port")
            return ""

        start_time = time.time()
        # ws: 飞桨语音识别后端WebSocket连接
        async with websockets.connect(self.url) as ws:
            # 发送开始信号
            audio_info = json.dumps(
                {
                    "name": "web_audio",
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

            # 启动音频处理器
            web_audio_handler.start()
            print("开始处理Web音频流...")

            # 用于检测静音的变量
            # TODO: 可以改进为基于音频能量的静音检测
            last_result = None
            last_result_time = None
            silence_timeout = 3  # 3秒

            # 处理音频数据
            for chunk_data in web_audio_handler.read_audio_stream():
                # 处理音频数据块
                chunk_data = chunk_data.astype(np.int16)
                await ws.send(chunk_data.tobytes())

                # 非阻塞接收消息
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.1)
                    msg = json.loads(msg)
                    current_result = msg.get("result", "")
                    print("client receive msg={}".format(msg))

                    if current_result:
                        # 发送实时结果到前端
                        if real_time_callback:
                            real_time_callback(current_result, msg.get("type", "partial"))

                    # 检查结果是否与上次相同
                    if current_result and current_result == last_result:
                        if last_result_time is None:
                            last_result_time = time.time()
                        elif time.time() - last_result_time >= silence_timeout:
                            print(
                                f"No speech detected for {silence_timeout} seconds, processing complete."
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
                    "name": "web_audio",
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

            # 停止音频处理器
            web_audio_handler.stop()

            # 添加标点
            if self.punc_server and len(msg["result"]) > 0:
                msg["result"] = self.punc_server.run(msg["result"])

            # 计算处理时间
            elapsed_time = time.time() - start_time
            print(f"elapsed time: {elapsed_time}")
            print(f"final result: {msg['result']}")

            return msg
