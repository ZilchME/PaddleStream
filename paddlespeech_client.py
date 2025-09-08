import asyncio

from audio_hander import ASRWsAudioHandler, TTSWsHandler


class ASROnlineClientExecutor:
    def __init__(self):
        pass

    def __call__(
        self,
        input: str,
        server_ip: str = "127.0.0.1",
        port: int = 8090,
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
            res = loop.run_until_complete(
                handler.run_web_audio(web_audio_handler, real_time_callback)
            )
        else:
            print("Unsupported input type or missing web_audio_handler")
            return ""

        print("asr websocket client finished")

        return res["result"] if res else ""


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
