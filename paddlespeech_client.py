import asyncio

from audio_hander import ASRWsAudioHandler


class ASROnlineClientExecutor:
    def __init__(self):
        pass

    def __call__(
        self,
        input: str,
        server_ip: str = "127.0.0.1",
        port: int = 8091,
        punc_server_ip: str = None,
        punc_server_port: str = None,
        web_audio_handler=None,
        real_time_callback=None,
    ):
        """Python API to call asr online executor.

        Args:
            input (str): the audio file to be send to streaming asr service or "mic" for microphone.
            server_ip (str, optional): streaming asr server ip. Defaults to "127.0.0.1".
            port (int, optional): streaming asr server port. Defaults to 8091.
            punc_server_ip (str, optional): punctuation server ip. Defaults to None.
            punc_server_port (str, optional): punctuation server port. Defaults to None.
            web_audio_handler: Web audio handler for processing web audio stream. Defaults to None.
            real_time_callback: Callback function for real-time results. Defaults to None.

        Returns:
            str: the audio text
        """

        print("asr websocket client start")
        handler = ASRWsAudioHandler(
            server_ip,
            port,
            punc_server_ip=punc_server_ip,
            punc_server_port=punc_server_port,
        )
        loop = asyncio.get_event_loop()
        
        if input == "mic":
            res = loop.run_until_complete(handler.run_mic())
        elif input == "web" and web_audio_handler is not None:
            res = loop.run_until_complete(handler.run_web_audio(web_audio_handler, real_time_callback))
        else:
            print("Unsupported input type or missing web_audio_handler")
            return ""

        print("asr websocket client finished")

        return res["result"] if res else ""
