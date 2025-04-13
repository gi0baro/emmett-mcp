import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from functools import partial
from typing import Any, Dict

from pydantic import BaseModel, Field, field_serializer

from .proto import MCPInterrupt


class TaskState(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"


class TaskStatus(BaseModel):
    state: TaskState
    timestamp: datetime = Field(default_factory=datetime.now)

    @field_serializer("timestamp")
    def serialize_dt(self, dt: datetime, _info):
        return dt.isoformat()


class Task(BaseModel):
    id: str
    inner: Any
    status: TaskStatus
    callback: Any = None
    metadata: dict[str, Any] | None = None


class TaskManager(ABC):
    @abstractmethod
    def add_task(self, id, task, callback, *args, **kwargs): ...

    @abstractmethod
    def cancel_task(self, id): ...

    @abstractmethod
    def _task_done(self, task: asyncio.Task, id: str): ...

    def message_task(self, reqid, session, proto, message, callback=None):
        self.add_task(reqid, self._message_task, callback, proto, session, message)

    async def _message_task(self, reqid, proto, session, message):
        try:
            if res := await proto.handle_message(session, message):
                await session.send((reqid, res))
        except MCPInterrupt as interrupt:
            self.cancel_task(interrupt.target)


class MemoryTaskManager(TaskManager):
    def __init__(self):
        self._tasks: Dict[str, Task] = {}

    def add_task(self, id, task, callback, *args, **kwargs):
        target = asyncio.create_task(task(id, *args, **kwargs))
        id = str(id)
        target.add_done_callback(partial(self._task_done, id=id))
        self._tasks[id] = Task(id=id, inner=target, status=TaskStatus(state=TaskState.PENDING), callback=callback)

    def cancel_task(self, id):
        id = str(id)
        if task := self._tasks.get(id):
            return task.inner.cancel()
        return False

    def _task_done(self, task: asyncio.Task, id: str):
        if obj := self._tasks.pop(id, None):
            if task.cancelled():
                obj.status.state = TaskState.CANCELED
            elif task.exception():
                obj.status.state = TaskState.FAILED
            else:
                obj.status.state = TaskState.COMPLETED
            if obj.callback:
                obj.callback(obj)
