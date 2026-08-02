from typing import List
from sqlalchemy import Column, String, Integer, DateTime, func, Float, UniqueConstraint, Text
import sqlalchemy as sa
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
import datetime

Base = declarative_base()

class ExtractedTable(Base):
    """
    Stores aligned financial/tabular data extracted from documents.
    """
    __tablename__ = 'extracted_tables'
    __table_args__ = (UniqueConstraint('document_id', 'node_id', 'row_index', name='uix_doc_node_row'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=True)
    document_id: Mapped[str] = mapped_column(String, index=True)
    node_id: Mapped[str] = mapped_column(String, index=True)
    row_index: Mapped[int] = mapped_column(Integer, default=0)
    source_page = Column(Integer, nullable=True)
    source_bbox = Column(ARRAY(Float), nullable=True)
    target_table: Mapped[str] = mapped_column(String, index=True)
    mapping_status: Mapped[str] = mapped_column(String)
    strict_columns = Column(JSONB, default=dict)
    unmapped_jsonb = Column(JSONB, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

class DocumentJob(Base):
    __tablename__ = 'document_jobs'
    document_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False, default="default-tenant")
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    current_stage: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    error_message = Column(String, nullable=True)
    s3_uri = Column(String(1024), nullable=True)
    file_hash = Column(String(255), nullable=True)
    sql_mapped = Column(sa.Boolean, nullable=False, server_default="false", default=False)
    vector_mapped = Column(sa.Boolean, nullable=False, server_default="false", default=False)
    graph_mapped = Column(sa.Boolean, nullable=False, server_default="false", default=False)
    sql_nodes_total = Column(Integer, nullable=False, server_default="0", default=0)
    sql_nodes_completed = Column(Integer, nullable=False, server_default="0", default=0)
    graph_nodes_total = Column(Integer, nullable=False, server_default="0", default=0)
    graph_nodes_completed = Column(Integer, nullable=False, server_default="0", default=0)
    
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

class Agent(Base):
    __tablename__ = 'agents'
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=True)
    system_prompt: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class AgentTask(Base):
    __tablename__ = 'agent_tasks'
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(255), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="QUEUED")
    prompt: Mapped[str] = mapped_column(Text, nullable=True)
    result = Column(String, nullable=True)
    locked_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

class DeadLetterQueue(Base):
    __tablename__ = 'dead_letter_queues'
    task_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(255), nullable=True)
    error: Mapped[str] = mapped_column(String, nullable=False)
    payload = Column(JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class HitlRequest(Base):
    __tablename__ = 'hitl_requests'
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING")
    error: Mapped[str] = mapped_column(String, nullable=False)
    payload = Column(JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class ExtractionCorrection(Base):
    """
    Durable HITL learning records: before/after patches, synonym remaps, eval promotion.
    """
    __tablename__ = "extraction_corrections"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    node_id: Mapped[str] = mapped_column(String(255), nullable=True)
    target_table: Mapped[str] = mapped_column(String(255), index=True, nullable=True)
    source_page = Column(Integer, nullable=True)
    source_bbox = Column(ARRAY(Float), nullable=True)
    critic_error = Column(Text, nullable=True)
    before_data = Column(JSONB, nullable=True)
    after_data = Column(JSONB, nullable=False)
    field_patches = Column(JSONB, nullable=True)
    synonym_mappings = Column(JSONB, nullable=True)
    reflexion_meta = Column(JSONB, nullable=True)
    hitl_request_id: Mapped[str] = mapped_column(String(255), nullable=True)
    promoted_to_eval: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default="false", default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
