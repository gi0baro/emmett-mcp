import asyncio
import uuid
from abc import ABC, abstractmethod

from emmett_core.sessions import SessionData


class MCPSessionData(SessionData):
    __slots__ = []

    def __init__(self, sid):
        super().__init__(sid=sid)
        self.initialized = False


class SessionManager(ABC):
    @abstractmethod
    def new(self) -> MCPSessionData: ...

    @abstractmethod
    def get(self, sid) -> MCPSessionData | None: ...

    @abstractmethod
    def store(self, data: MCPSessionData): ...

    @abstractmethod
    def drop(self, obj): ...


class MCPMemorySessionData(MCPSessionData):
    __slots__ = []

    def __init__(self, sid):
        super().__init__(sid)
        self.stream = asyncio.Queue()

    @property
    def send(self):
        return self.stream.put

    @property
    def recv(self):
        return self.stream.get


class MemorySessionManager(SessionManager):
    def __init__(self):
        self._data = {}

    def new(self):
        sid = uuid.uuid4().hex
        obj = MCPMemorySessionData(sid)
        self._data[sid] = obj
        return obj

    def get(self, sid):
        return self._data.get(sid)

    def store(self, data: MCPSessionData):
        if data._sid in self._data:
            return
        self._data[data._sid] = data

    def drop(self, obj):
        self._data.pop(obj._sid, None)
