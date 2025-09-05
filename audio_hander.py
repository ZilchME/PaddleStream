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

    def read_wave(self, wavfile_path: str):
        """read the audio file from specific wavfile path

        Args:
            wavfile_path (str): the audio wavfile,
                                 we assume that audio sample rate matches the model

        Yields:
            numpy.array: the samall package audio pcm data
        """
        samples, sample_rate = soundfile.read(wavfile_path, dtype="int16")
        x_len = len(samples)
        assert sample_rate == 16000

        chunk_size = int(85 * sample_rate / 1000)  # 85ms, sample_rate = 16kHz

        if x_len % chunk_size != 0:
            padding_len_x = chunk_size - x_len % chunk_size
        else:
            padding_len_x = 0

        padding = np.zeros((padding_len_x), dtype=samples.dtype)
        padded_x = np.concatenate([samples, padding], axis=0)

        assert (x_len + padding_len_x) % chunk_size == 0
        num_chunk = (x_len + padding_len_x) / chunk_size
        num_chunk = int(num_chunk)
        for i in range(0, num_chunk):
            start = i * chunk_size
            end = start + chunk_size
            x_chunk = padded_x[start:end]
            yield x_chunk

    def read_microphone(self):
        mic = MicrophoneHandler(sample_rate=16000)
        mic.start()
        print("麦克风已启动，按Enter键停止录音...")
        return mic

    async def run(self, wavfile_path: str):
        """Send a audio file to online server

        Args:
            wavfile_path (str): audio path

        Returns:
            str: the final asr result
        """
        logging.debug("send a message to the server")

        if self.url is None:
            print("No asr server, please input valid ip and port")
            return ""

        # 1. send websocket handshake protocol
        start_time = time.time()
        async with websockets.connect(self.url) as ws:
            # 2. server has already received handshake protocol
            # client start to send the command
            audio_info = json.dumps(
                {"name": "test.wav", "signal": "start", "nbest": 1},
                sort_keys=True,
                indent=4,
                separators=(",", ": "),
            )
            await ws.send(audio_info)
            msg = await ws.recv()
            print("client receive msg={}".format(msg))

            # 3. send chunk audio data to engine
            for chunk_data in self.read_wave(wavfile_path):
                await ws.send(chunk_data.tobytes())
                msg = await ws.recv()
                msg = json.loads(msg)
                print("client receive msg={}".format(msg))
            # client start to punctuation restore
            # if self.punc_server and len(msg["result"]) > 0:
            #     msg["result"] = self.punc_server.run(msg["result"])
            #     print("client punctuation restored msg={}".format(msg))
            # 4. we must send finished signal to the server
            audio_info = json.dumps(
                {"name": "test.wav", "signal": "end", "nbest": 1},
                sort_keys=True,
                indent=4,
                separators=(",", ": "),
            )
            await ws.send(audio_info)
            msg = await ws.recv()

            # 5. decode the bytes to str
            msg = json.loads(msg)

            if self.punc_server:
                msg["result"] = self.punc_server.run(msg["result"])

            # 6. logging the final result and comptute the statstics
            elapsed_time = time.time() - start_time
            audio_info = soundfile.info(wavfile_path)
            print("client final receive msg={}".format(msg))
            print(
                f"audio duration: {audio_info.duration}, elapsed time: {elapsed_time}, RTF={elapsed_time/audio_info.duration}"
            )

            result = msg

            return result

    async def run_mic(self):
        if self.url is None:
            print("No asr server, please input valid ip and port")
            return ""

        # 建立WebSocket连接
        start_time = time.time()
        async with websockets.connect(self.url) as ws:
            # 发送开始信号
            audio_info = json.dumps(
                {
                    "name": "live_audio",
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

            # 创建停止标志
            stop_event = threading.Event()

            # 如果是麦克风输入，启动键盘监听线程
            def wait_for_enter():
                input("")  # 等待用户按回车
                stop_event.set()

            threading.Thread(target=wait_for_enter, daemon=True).start()

            # 发送音频数据
            # 启动麦克风或读取音频文件
            mic_handler = self.read_microphone()
            input_gen = mic_handler.read_microphone
            print("请开始说话...")

            # 用于检测静音的变量
            last_result = None
            last_result_time = None
            silence_timeout = 3  # 3秒

            for chunk_data in input_gen():
                if stop_event.is_set():
                    break

                # 处理麦克风数据块
                chunk_data = chunk_data.astype(np.int16)
                await ws.send(chunk_data.tobytes())

                # 非阻塞接收消息
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.1)
                    msg = json.loads(msg)
                    current_result = msg.get("result", "")
                    print("client receive msg={}".format(msg))

                    # 检查结果是否与上次相同
                    if current_result and current_result == last_result:
                        if last_result_time is None:
                            last_result_time = time.time()
                        elif time.time() - last_result_time >= silence_timeout:
                            print(
                                f"No speech detected for {silence_timeout} seconds, closing connection."
                            )
                            stop_event.set()
                            break
                    else:
                        last_result = current_result
                        last_result_time = None

                except asyncio.TimeoutError:
                    continue

            # 发送结束信号
            audio_info = json.dumps(
                {
                    "name": "live_audio",
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

            # 停止麦克风
            mic_handler.stop()
            # 添加标点
            if self.punc_server and len(msg["result"]) > 0:
                msg["result"] = self.punc_server.run(msg["result"])

            # 计算处理时间
            elapsed_time = time.time() - start_time
            print(f"elapsed time: {elapsed_time}")
            print(f"final result: {msg['result']}")

            return msg
