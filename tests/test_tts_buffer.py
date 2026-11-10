import unittest
from unittest.mock import AsyncMock, Mock

from paddlestream.core.session_manager import SessionManager
from paddlestream.services.tts_service import TTSBufferSession, register_tts_handlers


class TTSBufferTests(unittest.TestCase):
    def test_small_buffers_split_without_losing_text(self):
        for size in (1, 2, 3, 4, 1000):
            with self.subTest(max_buffer_size=size):
                session = TTSBufferSession("client", 0, size, None, Mock())
                text = "你好世界" * (size + 1)
                sentences = session.add_text(text) + session.flush_buffer()
                self.assertTrue(all(sentences))
                self.assertEqual("".join(sentences), text)
                self.assertEqual(session.text_buffer, "")
                queued = []
                while not session.pending_sentences.empty():
                    queued.append(session.pending_sentences.get_nowait())
                self.assertEqual(queued, sentences)

    def test_invalid_buffer_sizes_are_rejected(self):
        for size in (0, -1, True, False, 1.5, "4", None):
            with self.subTest(max_buffer_size=size):
                with self.assertRaisesRegex(ValueError, "max_buffer_size"):
                    TTSBufferSession("client", 0, size, None, Mock())


class TTSBufferHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_start_does_not_replace_an_existing_session(self):
        sio = Mock()
        sio.event.side_effect = lambda handler: handler
        sio.emit = AsyncMock()
        manager = SessionManager()
        existing = Mock()
        manager.set_tts_buffer_session("client", existing)
        register_tts_handlers(sio, manager, Mock(), Mock())
        start = next(
            call.args[0] for call in sio.event.call_args_list
            if call.args[0].__name__ == "start_stream_tts"
        )

        await start("client", {"max_buffer_size": 0})

        self.assertIs(manager.get_tts_buffer_session("client"), existing)
        existing.stop_processing.assert_not_called()
        sio.emit.assert_awaited_once_with(
            "tts_error", {"error": "max_buffer_size 必须是正整数"}, room="client"
        )


if __name__ == "__main__":
    unittest.main()
