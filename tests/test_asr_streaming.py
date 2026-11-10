import asyncio
from collections import deque
import itertools
import json
import unittest
from unittest.mock import AsyncMock, Mock, call, patch

from paddlestream.clients.audio_handler import ASRWsAudioHandler, WebSocketAudioHandler


class FakeWebSocket:
    def __init__(self, responses, repeat_response=None):
        self.responses = deque(responses)
        self.repeat_response = repeat_response
        self.sent = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if self.responses:
            response = self.responses.popleft()
            if isinstance(response, Exception):
                raise response
            return json.dumps(response)
        if self.repeat_response is not None:
            await asyncio.sleep(0)
            return json.dumps(self.repeat_response)
        await asyncio.Event().wait()


class ASRStreamingTests(unittest.IsolatedAsyncioTestCase):
    def make_audio(self, chunks, stopped=True):
        audio = WebSocketAudioHandler()
        audio.start_processing()
        for chunk in chunks:
            audio.add_audio_data(chunk)
        if stopped:
            audio.stop_processing()
        return audio

    async def run_stream(self, audio, ws, callback=None, timeout=30):
        client = ASRWsAudioHandler(
            "asr.example", 8090, "/asr", final_result_timeout=timeout
        )
        client.punc_server = Mock()
        client.punc_server.run.side_effect = lambda text: text
        with (
            patch.object(client, "health_check", AsyncMock(return_value=True)),
            patch("paddlestream.clients.audio_handler.websockets.connect", return_value=ws),
        ):
            result = await client.run_websocket_audio(audio, callback)
        return result, client.punc_server

    async def test_stop_sends_all_queued_audio_before_end(self):
        for count in (0, 1, 3):
            with self.subTest(chunks=count):
                chunks = [bytes([index, 0]) * 10 for index in range(count)]
                ws = FakeWebSocket(
                    [{"signal": "server_ready"}]
                    + [{"result": "识别中"}] * count
                    + [{"signal": "finished", "result": "最终结果", "times": [1, 2]}]
                )
                result, punc = await self.run_stream(self.make_audio(chunks), ws)

                self.assertEqual(ws.sent[1:-1], chunks)
                self.assertEqual(json.loads(ws.sent[0])["signal"], "start")
                self.assertEqual(json.loads(ws.sent[-1])["signal"], "end")
                self.assertEqual(result["result"], "最终结果")
                self.assertEqual(result["times"], [1, 2])
                punc.run.assert_called_once_with("最终结果")
                self.assertTrue(ws.closed)

    async def test_backlogged_partials_do_not_become_final_result(self):
        callback = Mock()
        ws = FakeWebSocket([
            {"signal": "server_ready"},
            asyncio.TimeoutError(),
            {"result": "第一条中间结果"},
            {"result": "第二条中间结果", "type": "partial"},
            {"signal": "finished", "result": "最终结果"},
        ])
        result, punc = await self.run_stream(self.make_audio([b"\x01\x00"]), ws, callback)

        self.assertEqual(result, {"signal": "finished", "result": "最终结果"})
        self.assertEqual(
            callback.call_args_list,
            [call("第一条中间结果", "partial"), call("第二条中间结果", "partial")],
        )
        punc.run.assert_called_once_with("最终结果")

    async def test_upstream_finished_during_streaming_needs_no_end_request(self):
        chunk = b"\x01\x00"
        audio = self.make_audio([chunk], stopped=False)
        callback = Mock()
        ws = FakeWebSocket([
            {"signal": "server_ready"},
            {"signal": "finished", "result": "上游已结束"},
        ])
        result, _ = await self.run_stream(audio, ws, callback)

        self.assertEqual(result["result"], "上游已结束")
        self.assertEqual(len(ws.sent), 2)
        self.assertEqual(ws.sent[1], chunk)
        self.assertFalse(audio.is_receiving)
        callback.assert_not_called()

    async def test_repeated_transcripts_do_not_truncate_queued_audio(self):
        chunks = [b"\x01\x00"] * 5
        ws = FakeWebSocket(
            [{"signal": "server_ready"}]
            + [{"result": "相同的识别文本"}] * len(chunks)
            + [{"signal": "finished", "result": "最终结果"}]
        )
        with patch("paddlestream.clients.audio_handler.time") as clock:
            clock.time.side_effect = itertools.count(0, 4)
            await self.run_stream(self.make_audio(chunks), ws)
        self.assertEqual(ws.sent[1:-1], chunks)

    async def test_missing_finished_times_out_even_if_partials_keep_arriving(self):
        for repeat in (None, {"result": "尚未完成"}):
            with self.subTest(repeat=repeat):
                ws = FakeWebSocket([{"signal": "server_ready"}], repeat_response=repeat)
                with self.assertRaisesRegex(TimeoutError, "finished"):
                    await self.run_stream(self.make_audio([]), ws, timeout=0.02)
                self.assertTrue(ws.closed)

    async def test_disconnect_before_finished_does_not_return_partial(self):
        ws = FakeWebSocket([
            {"signal": "server_ready"},
            {"result": "尚未完成"},
            ConnectionError("upstream disconnected"),
        ])
        with self.assertRaises(ConnectionError):
            await self.run_stream(self.make_audio([]), ws)
        self.assertTrue(ws.closed)

    async def test_finished_requires_a_string_result(self):
        for result in (None, 42):
            with self.subTest(result=result):
                ws = FakeWebSocket([
                    {"signal": "server_ready"},
                    {"signal": "finished", "result": result},
                ])
                with self.assertRaisesRegex(ValueError, "result"):
                    await self.run_stream(self.make_audio([]), ws)

    async def test_empty_final_transcript_is_valid(self):
        ws = FakeWebSocket([
            {"signal": "server_ready"},
            {"signal": "finished", "result": ""},
        ])
        result, punc = await self.run_stream(self.make_audio([]), ws)
        self.assertEqual(result["result"], "")
        punc.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
