"""add dlq and hitl tables

Revision ID: fd108fda67f1
Revises: e23f05405b93
Create Date: 2026-08-01 17:30:06.926546

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'fd108fda67f1'
down_revision: Union[str, Sequence[str], None] = 'e23f05405b93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade() -> None:
    op.create_table(
        'dead_letter_queues',
        sa.Column('task_id', sa.String(length=255), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=False),
        sa.Column('document_id', sa.String(length=255), nullable=False),
        sa.Column('agent_name', sa.String(length=255), nullable=True),
        sa.Column('error', sa.String(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('task_id')
    )
    op.create_index(op.f('ix_dead_letter_queues_tenant_id'), 'dead_letter_queues', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_dead_letter_queues_document_id'), 'dead_letter_queues', ['document_id'], unique=False)

    op.create_table(
        'hitl_requests',
        sa.Column('id', sa.String(length=255), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=False),
        sa.Column('document_id', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='PENDING'),
        sa.Column('error', sa.String(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_hitl_requests_tenant_id'), 'hitl_requests', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_hitl_requests_document_id'), 'hitl_requests', ['document_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_hitl_requests_document_id'), table_name='hitl_requests')
    op.drop_index(op.f('ix_hitl_requests_tenant_id'), table_name='hitl_requests')
    op.drop_table('hitl_requests')

    op.drop_index(op.f('ix_dead_letter_queues_document_id'), table_name='dead_letter_queues')
    op.drop_index(op.f('ix_dead_letter_queues_tenant_id'), table_name='dead_letter_queues')
    op.drop_table('dead_letter_queues')
