from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class IngestEvent(_message.Message):
    __slots__ = ("event_id", "tenant_id", "s3_uri", "file_hash_sha256", "timestamp", "metadata")
    class MetadataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    S3_URI_FIELD_NUMBER: _ClassVar[int]
    FILE_HASH_SHA256_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    event_id: str
    tenant_id: str
    s3_uri: str
    file_hash_sha256: str
    timestamp: str
    metadata: _containers.ScalarMap[str, str]
    def __init__(self, event_id: _Optional[str] = ..., tenant_id: _Optional[str] = ..., s3_uri: _Optional[str] = ..., file_hash_sha256: _Optional[str] = ..., timestamp: _Optional[str] = ..., metadata: _Optional[_Mapping[str, str]] = ...) -> None: ...

class CitationPayload(_message.Message):
    __slots__ = ("document_id", "page", "normalized_coordinates", "quoted_text")
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    NORMALIZED_COORDINATES_FIELD_NUMBER: _ClassVar[int]
    QUOTED_TEXT_FIELD_NUMBER: _ClassVar[int]
    document_id: str
    page: int
    normalized_coordinates: _containers.RepeatedScalarFieldContainer[float]
    quoted_text: str
    def __init__(self, document_id: _Optional[str] = ..., page: _Optional[int] = ..., normalized_coordinates: _Optional[_Iterable[float]] = ..., quoted_text: _Optional[str] = ...) -> None: ...
