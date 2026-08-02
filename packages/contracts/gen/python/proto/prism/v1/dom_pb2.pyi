from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class NodeType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    NODE_TYPE_UNSPECIFIED: _ClassVar[NodeType]
    NODE_TYPE_TEXT: _ClassVar[NodeType]
    NODE_TYPE_TABLE: _ClassVar[NodeType]
    NODE_TYPE_IMAGE: _ClassVar[NodeType]
    NODE_TYPE_KEY_VALUE: _ClassVar[NodeType]
    NODE_TYPE_FORM: _ClassVar[NodeType]
    NODE_TYPE_SECTION_HEADER: _ClassVar[NodeType]
    NODE_TYPE_TITLE: _ClassVar[NodeType]
    NODE_TYPE_CHECKBOX: _ClassVar[NodeType]
    NODE_TYPE_CODE: _ClassVar[NodeType]
NODE_TYPE_UNSPECIFIED: NodeType
NODE_TYPE_TEXT: NodeType
NODE_TYPE_TABLE: NodeType
NODE_TYPE_IMAGE: NodeType
NODE_TYPE_KEY_VALUE: NodeType
NODE_TYPE_FORM: NodeType
NODE_TYPE_SECTION_HEADER: NodeType
NODE_TYPE_TITLE: NodeType
NODE_TYPE_CHECKBOX: NodeType
NODE_TYPE_CODE: NodeType

class Provenance(_message.Message):
    __slots__ = ("page_number", "bounding_box")
    PAGE_NUMBER_FIELD_NUMBER: _ClassVar[int]
    BOUNDING_BOX_FIELD_NUMBER: _ClassVar[int]
    page_number: int
    bounding_box: _containers.RepeatedScalarFieldContainer[float]
    def __init__(self, page_number: _Optional[int] = ..., bounding_box: _Optional[_Iterable[float]] = ...) -> None: ...

class Node(_message.Message):
    __slots__ = ("id", "type", "content", "provenance", "children")
    ID_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    PROVENANCE_FIELD_NUMBER: _ClassVar[int]
    CHILDREN_FIELD_NUMBER: _ClassVar[int]
    id: str
    type: NodeType
    content: str
    provenance: Provenance
    children: _containers.RepeatedCompositeFieldContainer[Node]
    def __init__(self, id: _Optional[str] = ..., type: _Optional[_Union[NodeType, str]] = ..., content: _Optional[str] = ..., provenance: _Optional[_Union[Provenance, _Mapping]] = ..., children: _Optional[_Iterable[_Union[Node, _Mapping]]] = ...) -> None: ...

class DocumentDOM(_message.Message):
    __slots__ = ("nodes", "metadata", "document_id")
    class MetadataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NODES_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    nodes: _containers.RepeatedCompositeFieldContainer[Node]
    metadata: _containers.ScalarMap[str, str]
    document_id: str
    def __init__(self, nodes: _Optional[_Iterable[_Union[Node, _Mapping]]] = ..., metadata: _Optional[_Mapping[str, str]] = ..., document_id: _Optional[str] = ...) -> None: ...
