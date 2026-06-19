import asyncio
import codecs
import http.client
import json
import re
import threading
import time
from typing import Optional
from urllib.parse import urlparse


def register_llm_handlers(sio, session_manager, llm_api_config, logger) -> None:
    """注册 LLM SSE 流式处理相关事件。"""

    @sio.event
    async def send_llm_message(sid, data):
        logger.info("收到LLM消息请求: %s", sid)
        try:
            input_text = data.get("input_text", "")
            llm_session_id = data.get("session_id", sid)

            if not input_text:
                await sio.emit("llm_error", {"error": "输入文本不能为空"}, room=sid)
                return

            cfg_url = None
            try:
                if isinstance(llm_api_config, dict):
                    cfg_url = llm_api_config.get("url")
            except Exception:
                cfg_url = None

            llm_api_url = data.get("llm_api_url") or cfg_url
            if not llm_api_url:
                await sio.emit(
                    "llm_error",
                    {
                        "error": "未配置LLM API地址，请在 config/settings.py 设置 LLM_API_CONFIG['url'] 或在请求中传入 llm_api_url",
                        "session_id": llm_session_id,
                    },
                    room=sid,
                )
                return

            llm_timeout = None
            try:
                if isinstance(llm_api_config, dict):
                    llm_timeout = llm_api_config.get("timeout")
            except Exception:
                llm_timeout = None

            if llm_timeout is None:
                await sio.emit(
                    "llm_error",
                    {
                        "error": "未配置LLM API超时时间，请在 .env 中设置 PADDLESTREAM_LLM_API_TIMEOUT",
                        "session_id": llm_session_id,
                    },
                    room=sid,
                )
                return

            await sio.emit("llm_stream_start", {"session_id": llm_session_id}, room=sid)
            await _process_llm_sse_stream(
                sio=sio,
                session_manager=session_manager,
                logger=logger,
                sid=sid,
                llm_api_url=llm_api_url,
                input_text=input_text,
                llm_session_id=llm_session_id,
                timeout=llm_timeout,
            )
        except Exception as e:
            logger.error("LLM消息处理错误: %s", e)
            await sio.emit("llm_error", {"error": str(e)}, room=sid)

    @sio.event
    async def cancel_llm_stream(sid, data=None):
        try:
            logger.info("取消LLM流请求: %s", sid)
            session_id = (data or {}).get("session_id") or sid

            entry = session_manager.get_llm_stream(session_id)
            if not entry:
                await sio.emit(
                    "llm_stream_not_found",
                    {
                        "session_id": session_id,
                        "message": "LLM stream not found or already finished.",
                    },
                    room=sid,
                )
                return

            try:
                if entry.get("stop_event"):
                    entry["stop_event"].set()
                if entry.get("conn"):
                    try:
                        entry["conn"].close()
                    except Exception:
                        pass
            except Exception as e:
                logger.error("Error while cancelling LLM stream %s: %s", session_id, e)

            try:
                session_manager.pop_llm_stream(session_id)
            except Exception:
                pass

            await sio.emit(
                "llm_stream_cancelled",
                {"session_id": session_id, "message": "Cancelled"},
                room=sid,
            )
        except Exception as e:
            logger.error("cancel_llm_stream error: %s", e)
            await sio.emit("llm_error", {"error": str(e)}, room=sid)


async def _process_llm_sse_stream(
    sio,
    session_manager,
    logger,
    sid: str,
    llm_api_url: str,
    input_text: str,
    llm_session_id: str,
    timeout: Optional[int] = None,
):
    try:
        request_data = {
            "input": {"human_input": input_text},
            "config": {"configurable": {"session_id": llm_session_id}},
        }

        loop = asyncio.get_running_loop()
        if timeout is None:
            raise ValueError("LLM API timeout 未配置，请设置 PADDLESTREAM_LLM_API_TIMEOUT")

        if session_manager.has_llm_stream(llm_session_id):
            prev = session_manager.get_llm_stream(llm_session_id)
            try:
                if prev and prev.get("stop_event"):
                    prev["stop_event"].set()
                if prev and prev.get("conn"):
                    try:
                        prev["conn"].close()
                    except Exception:
                        pass
            except Exception:
                pass

        stop_event = threading.Event()
        session_manager.set_llm_stream(llm_session_id, {"stop_event": stop_event, "conn": None})

        def on_content(content: str):
            asyncio.run_coroutine_threadsafe(
                sio.emit(
                    "llm_stream_content",
                    {"content": content, "session_id": llm_session_id},
                    room=sid,
                ),
                loop,
            )
            delay = 0
            if delay > 0:
                time.sleep(delay)

        def worker():
            try:
                _blocking_sse_post_and_parse(
                    llm_api_url=llm_api_url,
                    request_json=request_data,
                    on_content=on_content,
                    session_manager=session_manager,
                    session_id=llm_session_id,
                    timeout=timeout,
                )
            except Exception as e:
                try:
                    asyncio.run_coroutine_threadsafe(
                        sio.emit(
                            "llm_error",
                            {"error": str(e), "session_id": llm_session_id},
                            room=sid,
                        ),
                        loop,
                    )
                except Exception:
                    pass

        await asyncio.to_thread(worker)
        await sio.emit("llm_stream_complete", {"session_id": llm_session_id}, room=sid)
        logger.info("LLM流式响应处理完成: %s", sid)
        session_manager.pop_llm_stream(llm_session_id)
    except Exception as e:
        logger.error("LLM SSE流处理错误: %s", e)
        await sio.emit("llm_error", {"error": str(e), "session_id": llm_session_id}, room=sid)


def _blocking_sse_post_and_parse(
    llm_api_url: str,
    request_json: dict,
    on_content,
    session_manager,
    session_id: Optional[str] = None,
    read_chunk_size: int = 1024,
    timeout: Optional[int] = None,
):
    parsed = urlparse(llm_api_url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    port = parsed.port
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    if not host:
        raise ValueError(f"无效的LLM_API_URL: {llm_api_url}")
    if timeout is None:
        raise ValueError("LLM API timeout 未配置，请设置 PADDLESTREAM_LLM_API_TIMEOUT")

    if scheme == "https":
        conn = http.client.HTTPSConnection(host, port=port, timeout=timeout)
    elif scheme == "http":
        conn = http.client.HTTPConnection(host, port=port, timeout=timeout)
    else:
        raise ValueError(f"不支持的协议: {scheme}")

    try:
        if session_id:
            llm_entry = session_manager.get_llm_stream(session_id)
            if llm_entry is not None:
                llm_entry["conn"] = conn
    except Exception:
        pass

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    body = json.dumps(request_json).encode("utf-8")
    conn.request("POST", path, body=body, headers=headers)
    resp = conn.getresponse()

    if resp.status != 200:
        error_text = resp.read().decode("utf-8", errors="ignore")
        conn.close()
        raise RuntimeError(f"LLM API请求失败: {resp.status} - {error_text}")

    decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""

    try:
        while True:
            if session_id:
                entry = session_manager.get_llm_stream(session_id)
                if entry and entry.get("stop_event") and entry["stop_event"].is_set():
                    try:
                        conn.close()
                    except Exception:
                        pass
                    break

            try:
                chunk = resp.read(read_chunk_size)
            except Exception:
                break

            if not chunk:
                break

            buffer += decoder.decode(chunk, final=False)
            event_blocks = re.split(r"(?:\r?\n){2}", buffer)

            if len(event_blocks) > 1:
                for block in event_blocks[:-1]:
                    block = block.strip()
                    if not block:
                        continue
                    _process_sse_block_sync(block, on_content)
                buffer = event_blocks[-1]

        tail = decoder.decode(b"", final=True)
        if tail:
            buffer += tail
        if buffer.strip():
            _process_sse_block_sync(buffer.strip(), on_content)
    finally:
        try:
            conn.close()
        except Exception:
            pass
        try:
            if session_id and session_manager.has_llm_stream(session_id):
                session_manager.update_llm_stream(session_id, conn=None)
        except Exception:
            pass


def _process_sse_block_sync(block: str, on_content):
    lines = block.splitlines()
    for line in lines:
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue
        json_str = re.sub(r"^data:\s*", "", line)
        if not json_str or json_str.strip() == "[DONE]":
            continue
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            continue
        content = data.get("content")
        if content:
            on_content(content)
