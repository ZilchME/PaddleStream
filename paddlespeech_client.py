import asyncio
import json
import time
from typing import Callable, Optional

from audio_hander import ASRWsAudioHandler, WebSocketAudioHandler, TTSWsHandler


class ASROnlineClientExecutor:
    def __init__(self):
        pass

    def process_websocket_audio(
        self,
        audio_handler: WebSocketAudioHandler,
        server_ip: str = "127.0.0.1",
        port: int = 8091,
        punc_server_ip: str = None,
        punc_server_port: str = None,
        real_time_callback=None,
    ):
        """处理来自WebSocket的音频数据

        Args:
            audio_handler (WebSocketAudioHandler): WebSocket音频处理器
            server_ip (str, optional): streaming asr server ip. Defaults to "127.0.0.1".
            port (int, optional): streaming asr server port. Defaults to 8091.
            punc_server_ip (str, optional): punctuation server ip. Defaults to None.
            punc_server_port (str, optional): punctuation server port. Defaults to None.

        Returns:
            str: the audio text
        """
        print("asr websocket client start for web audio")
        handler = ASRWsAudioHandler(
            url=server_ip,
            port=port,
            endpoint="/paddlespeech/asr/streaming",
            punc_server_ip=punc_server_ip,
            punc_server_port=punc_server_port,
        )

        # 创建新的事件循环
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        res = loop.run_until_complete(
            handler.run_websocket_audio(
                audio_handler, real_time_callback=real_time_callback
            )
        )
        print("asr websocket client finished for web audio")

        return res["result"]


class TTSOnlineClientExecutor:
    def __init__(self):
        pass

    def __call__(
        self,
        input: str,
        server_ip: str = "127.0.0.1",
        port: int = 8090,
        spk_id: int = 0,
        output: str = None,
        play: bool = False,
    ):
        """
        Python API to call an executor.
        """

        print("tts websocket client start")
        handler = TTSWsHandler(server_ip, port, play)
        loop = asyncio.get_event_loop()
        (
            first_response,
            final_response,
            duration,
            save_audio_success,
            receive_time_list,
            chunk_duration_list,
        ) = loop.run_until_complete(handler.run(input, spk_id, output))
        delay_time_list = compute_delay(receive_time_list, chunk_duration_list)

        print(f"sentence: {input}")
        print(f"duration: {duration} s")
        print(f"first response: {first_response} s")
        print(f"final response: {final_response} s")
        print(f"RTF: {final_response/duration}")
        if output is not None:
            if save_audio_success:
                print(f"Audio successfully saved in {output}")
            else:
                print("Audio save failed.")

        if delay_time_list != []:
            print(
                f"Delay situation: total number of packages: {len(receive_time_list)}, the number of delayed packets: {len(delay_time_list)}, minimum delay time: {min(delay_time_list)} s, maximum delay time: {max(delay_time_list)} s, average delay time: {sum(delay_time_list)/len(delay_time_list)} s, delay rate:{len(delay_time_list)/len(receive_time_list)}"
            )
        else:
            print("The sentence has no delay in streaming synthesis.")


def compute_delay(receive_time_list, chunk_duration_list):
    """compute delay
    Args:
        receive_time_list (list): Time to receive each packet
        chunk_duration_list (list): The audio duration corresponding to each packet
    Returns:
        [list]: Delay time list
    """
    assert len(receive_time_list) == len(chunk_duration_list)
    delay_time_list = []
    play_time = receive_time_list[0] + chunk_duration_list[0]
    for i in range(1, len(receive_time_list)):
        receive_time = receive_time_list[i]
        delay_time = receive_time - play_time
        # 有延迟
        if delay_time > 0:
            play_time = play_time + delay_time + chunk_duration_list[i]
            delay_time_list.append(delay_time)
        # 没有延迟
        else:
            play_time = play_time + chunk_duration_list[i]

    return delay_time_list


class WebTTSSession:
    """Web TTS会话处理类，用于处理单个客户端的TTS请求"""

    def __init__(self, session_id: str, server_ip: str = "127.0.0.1", port: int = 8092):
        self.session_id = session_id
        self.server_ip = server_ip
        self.port = port
        self.handler = TTSWsHandler(server_ip, port, play=False)
        self.is_processing = False
        self.stream_callback: Optional[Callable] = None

    def set_stream_callback(self, callback: Callable):
        """设置流式音频数据回调函数"""
        self.stream_callback = callback

    async def synthesize_text_stream(self, text: str, spk_id: int = 0):
        """
        流式合成文本并通过回调函数返回音频数据

        Args:
            text (str): 要合成的文本
            spk_id (int): 说话人ID

        Returns:
            dict: 包含合成结果的字典
        """
        if self.is_processing:
            return {"status": "error", "message": "Already processing"}

        self.is_processing = True

        try:
            # 使用修改后的TTS处理器进行流式合成
            result = await self._run_streaming_tts(text, spk_id)
            return result
        except Exception as e:
            print(f"TTS synthesis error: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            self.is_processing = False

    async def _run_streaming_tts(self, text: str, spk_id: int = 0):
        """运行流式TTS合成"""
        import websockets

        url = f"ws://{self.server_ip}:{self.port}/paddlespeech/tts/streaming"

        async with websockets.connect(url) as ws:
            # 发送开始请求
            start_request = json.dumps({"task": "tts", "signal": "start"})
            await ws.send(start_request)
            msg = await ws.recv()
            print(f"TTS server response: {msg}")
            msg = json.loads(msg)
            session = msg["session"]

            # 发送合成请求
            params = {
                "text": text,
                "spk_id": spk_id,
            }
            request = json.dumps(params)
            start_time = time.time()
            await ws.send(request)

            # 处理流式响应
            total_chunks = 0
            first_chunk_time = None

            while True:
                try:
                    message = await ws.recv()
                    message = json.loads(message)
                    status = message["status"]

                    if status == -1:  # 错误
                        # 发送结束请求
                        end_request = json.dumps(
                            {"task": "tts", "signal": "end", "session": session}
                        )
                        await ws.send(end_request)
                        return {"status": "error", "message": "TTS synthesis failed"}

                    elif status == 2:  # 最后一包，合成完成
                        end_time = time.time()
                        total_time = end_time - start_time

                        # 发送结束请求
                        end_request = json.dumps(
                            {"task": "tts", "signal": "end", "session": session}
                        )
                        await ws.send(end_request)

                        # 发送完成信号到客户端
                        if self.stream_callback:
                            await self.stream_callback(
                                {
                                    "type": "synthesis_complete",
                                    "session_id": self.session_id,
                                    "total_time": total_time,
                                    "total_chunks": total_chunks,
                                    "first_chunk_time": first_chunk_time,
                                }
                            )

                        return {
                            "status": "completed",
                            "total_time": total_time,
                            "total_chunks": total_chunks,
                            "first_chunk_time": first_chunk_time,
                        }

                    elif status == 1:  # 音频数据
                        if first_chunk_time is None:
                            first_chunk_time = time.time() - start_time

                        audio_data = message["audio"]
                        total_chunks += 1

                        # 通过回调函数发送音频数据到客户端
                        if self.stream_callback:
                            await self.stream_callback(
                                {
                                    "type": "audio_chunk",
                                    "session_id": self.session_id,
                                    "audio_data": audio_data,  # Base64编码的音频数据
                                    "chunk_index": total_chunks,
                                    "timestamp": time.time(),
                                }
                            )

                except Exception as e:
                    print(f"Error receiving TTS data: {e}")
                    break

        return {"status": "error", "message": "Connection closed unexpectedly"}


class TTSWebServerExecutor:
    """Web TTS服务执行器，管理多个TTS会话"""

    def __init__(self, server_ip: str = "127.0.0.1", port: int = 8092):
        self.server_ip = server_ip
        self.port = port
        self.sessions = {}  # 存储活跃的TTS会话

    def create_session(self, session_id: str) -> WebTTSSession:
        """创建新的TTS会话"""
        if session_id in self.sessions:
            # 如果会话已存在，先清理
            self.remove_session(session_id)

        session = WebTTSSession(session_id, self.server_ip, self.port)
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[WebTTSSession]:
        """获取现有会话"""
        return self.sessions.get(session_id)

    def remove_session(self, session_id: str):
        """移除会话"""
        if session_id in self.sessions:
            self.sessions[session_id].is_processing = False
            del self.sessions[session_id]

    async def synthesize_text(
        self,
        session_id: str,
        text: str,
        spk_id: int = 0,
        stream_callback: Optional[Callable] = None,
    ):
        """
        为指定会话合成文本

        Args:
            session_id (str): 会话ID
            text (str): 要合成的文本
            spk_id (int): 说话人ID
            stream_callback (Callable): 流式数据回调函数

        Returns:
            dict: 合成结果
        """
        session = self.get_session(session_id)
        if not session:
            session = self.create_session(session_id)
        else:
            # 如果会话已存在，重置处理状态以允许新的合成请求
            session.is_processing = False

        if stream_callback:
            session.set_stream_callback(stream_callback)

        result = await session.synthesize_text_stream(text, spk_id)
        return result


if __name__ == "__main__":
    ttsclient_executor = TTSOnlineClientExecutor()
    res = ttsclient_executor(
        input="测试语音合成",
        server_ip="127.0.0.1",
        port=8090,
        spk_id=0,
        output="tts_output.wav",
        play=False,
    )
