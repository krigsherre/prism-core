"""init

Revision ID: 9df258918886
Revises: 
Create Date: 2026-07-24 05:59:58.564951

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9df258918886'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'extracted_tables',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('document_id', sa.String(), nullable=False),
        sa.Column('node_id', sa.String(), nullable=False),
        sa.Column('content', sa.String(), nullable=False),
        sa.Column('source_page', sa.Integer(), nullable=False),
        sa.Column('source_bbox', sa.ARRAY(sa.Float()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_extracted_tables_document_id'), 'extracted_tables', ['document_id'], unique=False)
    op.create_index(op.f('ix_extracted_tables_node_id'), 'extracted_tables', ['node_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_extracted_tables_node_id'), table_name='extracted_tables')
    op.drop_index(op.f('ix_extracted_tables_document_id'), table_name='extracted_tables')
    op.drop_table('extracted_tables')
