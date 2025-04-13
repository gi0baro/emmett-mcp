from __future__ import annotations

from typing import Type

from emmett_core.extensions import Extension

from ._compat import AppModule
from .mcp import MCPModule
from .proto import (
    MCPBinaryResource,
    MCPDirectoryResource,
    MCPFileResource,
    MCPHttpResource,
    MCPTextResource,
)
from .sessions import MemorySessionManager
from .tasks import MemoryTaskManager
from .wrappers import wrap_method_on_obj, wrap_module_from_app, wrap_module_from_module


class MCP(Extension):
    default_config = {
        "default_module_class": MCPModule,
        "sse": True,
        "ws": True,
        "messages_path": "/messages",
        "sse_path": "/",
        "ws_path": "/",
        "persistence": "memory",
    }

    BinaryResource = MCPBinaryResource
    DirectoryResource = MCPDirectoryResource
    FileResource = MCPFileResource
    HttpResource = MCPHttpResource
    TextResource = MCPTextResource

    def on_load(self):
        AppModule.mcp_module = wrap_module_from_module(self)
        self.app.mcp_module = wrap_method_on_obj(wrap_module_from_app(self), self.app)
        # TODO: for future impl, based on self.config.persistence
        self._session_manager = MemorySessionManager()
        self._task_manager = MemoryTaskManager()

    @property
    def module(self) -> Type[MCPModule]:
        return self.config.default_module_class
