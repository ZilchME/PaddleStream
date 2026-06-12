from __future__ import annotations

import threading
from typing import Any, Dict, Optional


class SessionManager:
    """Thread-safe registry for ASR, TTS, and LLM session state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._asr_sessions: Dict[str, Any] = {}
        self._tts_buffer_sessions: Dict[str, Any] = {}
        self._llm_streams: Dict[str, Dict[str, Any]] = {}

    def get_asr_session(self, session_id: str) -> Optional[Any]:
        with self._lock:
            return self._asr_sessions.get(session_id)

    def set_asr_session(self, session_id: str, session: Any) -> None:
        with self._lock:
            self._asr_sessions[session_id] = session

    def pop_asr_session(self, session_id: str) -> Optional[Any]:
        with self._lock:
            return self._asr_sessions.pop(session_id, None)

    def has_asr_session(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._asr_sessions

    def get_tts_buffer_session(self, session_id: str) -> Optional[Any]:
        with self._lock:
            return self._tts_buffer_sessions.get(session_id)

    def set_tts_buffer_session(self, session_id: str, session: Any) -> None:
        with self._lock:
            self._tts_buffer_sessions[session_id] = session

    def pop_tts_buffer_session(self, session_id: str) -> Optional[Any]:
        with self._lock:
            return self._tts_buffer_sessions.pop(session_id, None)

    def has_tts_buffer_session(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._tts_buffer_sessions

    def get_llm_stream(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._llm_streams.get(session_id)

    def set_llm_stream(self, session_id: str, state: Dict[str, Any]) -> None:
        with self._lock:
            self._llm_streams[session_id] = state

    def update_llm_stream(self, session_id: str, **updates: Any) -> None:
        with self._lock:
            entry = self._llm_streams.setdefault(session_id, {})
            entry.update(updates)

    def pop_llm_stream(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._llm_streams.pop(session_id, None)

    def has_llm_stream(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._llm_streams

    def clear_socket_sessions(self, socket_id: str) -> None:
        """Remove ASR/TTS sessions attached to a socket id."""
        with self._lock:
            self._asr_sessions.pop(socket_id, None)
            self._tts_buffer_sessions.pop(socket_id, None)

