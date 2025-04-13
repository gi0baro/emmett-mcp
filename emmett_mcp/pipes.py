from emmett_core.pipeline import Pipe
from mcp_min.types import JSONRPCMessage
from pydantic_core import ValidationError

from ._compat import SSEPipe, abort, current


class MCPSessionPipe(Pipe):
    def __init__(self, session_manager):
        self.sessions = session_manager

    def pipe_request(self, next_pipe, **kwargs):
        session_id = current.request.query_params.session_id
        if not session_id:
            abort(400, "session_id is required")
        session = self.sessions.get(session_id)
        if not session:
            abort(404, "Session not found")
        current.mcp_session = session
        return next_pipe(**kwargs)


class MCPMessagePipe(Pipe):
    async def pipe_request(self, next_pipe, **kwargs):
        try:
            message = JSONRPCMessage.model_validate_json(await current.request.body)
            current.response.code = 202
        except ValidationError:
            current.response.code = 400
            return b"Cannot parse message"
        kwargs["message"] = message
        return await next_pipe(**kwargs)


class MCPSSEPipe(SSEPipe):
    def __init__(self, session_manager):
        super().__init__()
        self.sessions = session_manager

    async def open(self):
        current.mcp_session = self.sessions.new()

    async def close(self):
        self.sessions.drop(current.mcp_session)


class MCPWSPipe(Pipe):
    async def pipe_ws(self, next_pipe, **kwargs):
        await current.websocket.accept(subprotocol="mcp")
        return await next_pipe(**kwargs)

    def on_receive(self, data):
        try:
            data = JSONRPCMessage.model_validate_json(data)
        except ValidationError as exc:
            data = exc
        return data

    def on_send(self, data):
        return data.model_dump_json(by_alias=True, exclude_none=True)
