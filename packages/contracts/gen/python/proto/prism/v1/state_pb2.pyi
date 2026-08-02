from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AgentStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    AGENT_STATUS_UNSPECIFIED: _ClassVar[AgentStatus]
    AGENT_STATUS_IDLE: _ClassVar[AgentStatus]
    AGENT_STATUS_PROCESSING: _ClassVar[AgentStatus]
    AGENT_STATUS_COMPLETED: _ClassVar[AgentStatus]
    AGENT_STATUS_FAILED: _ClassVar[AgentStatus]
AGENT_STATUS_UNSPECIFIED: AgentStatus
AGENT_STATUS_IDLE: AgentStatus
AGENT_STATUS_PROCESSING: AgentStatus
AGENT_STATUS_COMPLETED: AgentStatus
AGENT_STATUS_FAILED: AgentStatus

class AgentState(_message.Message):
    __slots__ = ("agent_id", "status", "last_updated", "context")
    class ContextEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    LAST_UPDATED_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    agent_id: str
    status: AgentStatus
    last_updated: str
    context: _containers.ScalarMap[str, str]
    def __init__(self, agent_id: _Optional[str] = ..., status: _Optional[_Union[AgentStatus, str]] = ..., last_updated: _Optional[str] = ..., context: _Optional[_Mapping[str, str]] = ...) -> None: ...
