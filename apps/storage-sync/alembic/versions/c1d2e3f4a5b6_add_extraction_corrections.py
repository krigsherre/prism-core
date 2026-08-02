"""add extraction_corrections for HITL learning flywheel

Revision ID: c1d2e3f4a5b6
Revises: 9faafc16bb59
Create Date: 2026-08-02 14:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "9faafc16bb59"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "extraction_corrections",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("document_id", sa.String(length=255), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=True),
        sa.Column("target_table", sa.String(length=255), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_bbox", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("critic_error", sa.Text(), nullable=True),
        sa.Column("before_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("field_patches", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("synonym_mappings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reflexion_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("hitl_request_id", sa.String(length=255), nullable=True),
        sa.Column("promoted_to_eval", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extraction_corrections_tenant_id", "extraction_corrections", ["tenant_id"]
    )
    op.create_index(
        "ix_extraction_corrections_document_id", "extraction_corrections", ["document_id"]
    )
    op.create_index(
        "ix_extraction_corrections_target_table", "extraction_corrections", ["target_table"]
    )
    op.create_index(
        "ix_extraction_corrections_created_at", "extraction_corrections", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_extraction_corrections_created_at", table_name="extraction_corrections")
    op.drop_index("ix_extraction_corrections_target_table", table_name="extraction_corrections")
    op.drop_index("ix_extraction_corrections_document_id", table_name="extraction_corrections")
    op.drop_index("ix_extraction_corrections_tenant_id", table_name="extraction_corrections")
    op.drop_table("extraction_corrections")
