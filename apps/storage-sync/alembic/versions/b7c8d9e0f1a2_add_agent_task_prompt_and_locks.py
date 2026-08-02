"""add prompt and lock columns to agent_tasks

Revision ID: b7c8d9e0f1a2
Revises: fd108fda67f1
Create Date: 2026-08-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "fd108fda67f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_tasks", sa.Column("prompt", sa.Text(), nullable=True))
    op.add_column("agent_tasks", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_tasks", sa.Column("locked_by", sa.String(length=255), nullable=True))
    op.create_index("ix_agent_tasks_status_created", "agent_tasks", ["status", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_tasks_status_created", table_name="agent_tasks")
    op.drop_column("agent_tasks", "locked_by")
    op.drop_column("agent_tasks", "locked_at")
    op.drop_column("agent_tasks", "prompt")
