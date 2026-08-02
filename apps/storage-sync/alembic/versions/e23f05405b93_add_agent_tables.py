"""add agent tables

Revision ID: e23f05405b93
Revises: 03c19af9b404
Create Date: 2026-08-01 17:21:04.660024

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e23f05405b93'
down_revision: Union[str, Sequence[str], None] = '03c19af9b404'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agents',
        sa.Column('id', sa.String(length=255), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=1024), nullable=True),
        sa.Column('system_prompt', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agents_tenant_id'), 'agents', ['tenant_id'], unique=False)

    op.create_table(
        'agent_tasks',
        sa.Column('id', sa.String(length=255), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=False),
        sa.Column('agent_id', sa.String(length=255), nullable=False),
        sa.Column('document_id', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('result', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_tasks_agent_id'), 'agent_tasks', ['agent_id'], unique=False)
    op.create_index(op.f('ix_agent_tasks_document_id'), 'agent_tasks', ['document_id'], unique=False)
    op.create_index(op.f('ix_agent_tasks_tenant_id'), 'agent_tasks', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_agent_tasks_tenant_id'), table_name='agent_tasks')
    op.drop_index(op.f('ix_agent_tasks_document_id'), table_name='agent_tasks')
    op.drop_index(op.f('ix_agent_tasks_agent_id'), table_name='agent_tasks')
    op.drop_table('agent_tasks')
    
    op.drop_index(op.f('ix_agents_tenant_id'), table_name='agents')
    op.drop_table('agents')
