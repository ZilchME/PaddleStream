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
    ):
        """Python API to call asr online executor.

        Args:
            input (str): the audio file to be send to streaming asr service.
            server_ip (str, optional): streaming asr server ip. Defaults to "127.0.0.1".
            port (int, optional): streaming asr server port. Defaults to 8091.
            punc_server_ip (str, optional): punctuation server ip. Defaults to None.
            punc_server_port (str, optional): punctuation server port. Defaults to None.

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
        else:
            res = loop.run_until_complete(handler.run(input))
        print("asr websocket client finished")

        return res["result"]
