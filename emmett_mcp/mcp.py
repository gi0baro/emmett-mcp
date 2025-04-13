from __future__ import annotations

import asyncio
import inspect
import re
from typing import Any, Dict, Optional

from emmett_core.app import AppModule
from emmett_core.extensions import Extension
from emmett_core.http.wrappers.response import ServerSentEvent
from mcp_min.server.prompts import Prompt, PromptManager
from mcp_min.server.resources import FunctionResource, ResourceManager
from mcp_min.server.tools import ToolManager
from mcp_min.types import ErrorData, JSONRPCError, JSONRPCMessage, JSONRPCResponse
from pydantic.networks import AnyUrl

from ._compat import current, url
from .pipes import MCPMessagePipe, MCPSessionPipe, MCPSSEPipe, MCPWSPipe
from .proto import MCPProto


class MCPModule(AppModule):
    @classmethod
    def from_app(
        cls,
        ext: Extension,
        import_name: str,
        name: str,
        sse: bool = True,
        ws: bool = True,
        messages_path: Optional[str] = None,
        sse_path: Optional[str] = None,
        ws_path: Optional[str] = None,
        url_prefix: Optional[str] = None,
        hostname: Optional[str] = None,
        opts: Dict[str, Any] = {},
    ) -> MCPModule:
        return cls(
            ext,
            name,
            import_name,
            sse=sse,
            ws=ws,
            messages_path=messages_path,
            sse_path=sse_path,
            ws_path=ws_path,
            url_prefix=url_prefix,
            hostname=hostname,
            **opts,
        )

    @classmethod
    def from_module(
        cls,
        ext: Extension,
        mod: AppModule,
        import_name: str,
        name: str,
        sse: bool = True,
        ws: bool = True,
        messages_path: Optional[str] = None,
        sse_path: Optional[str] = None,
        ws_path: Optional[str] = None,
        url_prefix: Optional[str] = None,
        hostname: Optional[str] = None,
        opts: Dict[str, Any] = {},
    ) -> MCPModule:
        if "." in name:
            raise RuntimeError("Nested app modules' names should not contains dots")
        name = mod.name + "." + name
        if url_prefix and not url_prefix.startswith("/"):
            url_prefix = "/" + url_prefix
        module_url_prefix = (mod.url_prefix + (url_prefix or "")) if mod.url_prefix else url_prefix
        hostname = hostname or mod.hostname
        return cls(
            ext,
            name,
            import_name,
            sse=sse,
            ws=ws,
            messages_path=messages_path,
            sse_path=sse_path,
            ws_path=ws_path,
            url_prefix=module_url_prefix,
            hostname=hostname,
            pipeline=mod.pipeline,
            **opts,
        )

    def __init__(
        self,
        ext: Extension,
        name: str,
        import_name: str,
        sse: bool = True,
        ws: bool = True,
        messages_path: Optional[str] = None,
        sse_path: Optional[str] = None,
        ws_path: Optional[str] = None,
        url_prefix: Optional[str] = None,
        hostname: Optional[str] = None,
        **kwargs: Any,
    ):
        #: initialize
        super().__init__(ext.app, name, import_name, url_prefix=url_prefix, hostname=hostname, **kwargs)
        self.ext = ext

        self._proto_sse = sse or self.ext.config.sse
        self._proto_ws = ws or self.ext.config.ws
        if not self._proto_sse and not self._proto_ws:
            raise RuntimeError("Need at least one protocol")

        self._path_messages = messages_path or self.ext.config.messages_path
        self._path_sse = sse_path or self.ext.config.sse_path
        self._path_ws = ws_path or self.ext.config.ws_path

        self._mcp = MCPProto(self)

        self._manager_prompts = PromptManager()
        self._manager_resources = ResourceManager()
        self._manager_tools = ToolManager()

        self._init_pipelines()
        #: custom init
        self.init()
        #: configure module
        self._after_initialize()

    def _init_pipelines(self):
        self._pipeline_messages = [MCPSessionPipe(self.ext._session_manager), MCPMessagePipe()]
        self._pipeline_sse = [MCPSSEPipe(self.ext._session_manager)]
        self._pipeline_ws = [MCPWSPipe()]

    def init(self):
        pass

    def _after_initialize(self):
        self._expose_routes()

    def _expose_routes(self):
        self.route(
            self._path_messages, pipeline=self._pipeline_messages, methods="post", name="messages", output="bytes"
        )(self._messages)
        if self._proto_sse:
            self.route(self._path_sse, pipeline=self._pipeline_sse, methods="get", name="sse")(self._sse)
        # TODO
        # if self._proto_ws:
        #     self.websocket(self._path_ws, pipeline=self._pipeline_ws, name="ws")(self._ws)

    #: deafult routes
    async def _messages(self, message):
        self.ext._task_manager.message_task(getattr(message.root, "id", None), current.mcp_session, self._mcp, message)
        return b"Accepted"

    async def _sse(self):
        session_uri = url(".messages", params={"session_id": current.mcp_session._sid})
        yield ServerSentEvent(event="endpoint", data=session_uri)

        while True:
            req_id, message = await current.mcp_session.recv()
            if isinstance(message, ErrorData):
                data = JSONRPCError(jsonrpc="2.0", id=req_id, error=message)
            else:
                data = JSONRPCResponse(
                    jsonrpc="2.0",
                    id=req_id,
                    result=message.model_dump(by_alias=True, mode="json", exclude_none=True),
                )
            yield ServerSentEvent(
                event="message", data=JSONRPCMessage(data).model_dump(mode="json", by_alias=True, exclude_none=True)
            )

    # TODO: init streams
    async def _ws(self, stream_in: asyncio.Queue, stream_out: asyncio.Queue):
        async def recv():
            while True:
                message = await current.websocket.receive()
                # TODO: change to use task manager
                stream_in.put_nowait(message)

        async def send():
            while True:
                message = await stream_out.get()
                # TODO: build `JSONRPCMessage` objs
                await current.websocket.send(message)

        tasks = [asyncio.create_task(send()), asyncio.create_task(recv())]
        await asyncio.gather(*tasks)

    #: decorators
    def prompt(self, name: str | None = None, description: str | None = None):
        def deco(fn):
            prompt = Prompt.from_function(fn, name=name, description=description)
            self._manager_prompts.add_prompt(prompt)
            return fn

        return deco

    def resource(
        self,
        uri: str,
        *,
        name: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
    ):
        def deco(fn):
            # Check if this should be a template
            has_uri_params = "{" in uri and "}" in uri
            has_func_params = bool(inspect.signature(fn).parameters)

            if has_uri_params or has_func_params:
                # Validate that URI params match function params
                uri_params = set(re.findall(r"{(\w+)}", uri))
                func_params = set(inspect.signature(fn).parameters.keys())

                if uri_params != func_params:
                    raise ValueError(
                        f"Mismatch between URI parameters {uri_params} and function parameters {func_params}"
                    )

                # Register as template
                self._manager_resources.add_template(
                    fn=fn,
                    uri_template=uri,
                    name=name,
                    description=description,
                    mime_type=mime_type or "text/plain",
                )
            else:
                # Register as regular resource
                resource = FunctionResource(
                    uri=AnyUrl(uri),
                    name=name,
                    description=description,
                    mime_type=mime_type or "text/plain",
                    fn=fn,
                )
                self._manager_resources.add_resource(resource)
            return fn

        return deco

    def tool(self, name: str | None = None, description: str | None = None):
        def deco(fn):
            self._manager_tools.add_tool(fn, name=name, description=description)
            return fn

        return deco

    # def messages(self, pipeline=[]):
    #     pipeline = self.messages_pipeline + pipeline
    #     return self.route(self._path_base, pipeline=pipeline, methods="post", name="messages")

    # def sse(self, pipeline=[]):
    #     pipeline = self.sse_pipeline + pipeline
    #     return self.route(self._path_rid, pipeline=pipeline, methods="get", name="sse")

    # def ws(self, pipeline=[]):
    #     pipeline = self.ws_pipeline + pipeline
    #     return self.websocket(self._path_base, pipeline=pipeline, name="ws")
