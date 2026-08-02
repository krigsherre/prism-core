"""Add node tracking columns to document_jobs

Revision ID: f2c3b4a5e6d7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-02

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f2c3b4a5e6d7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('document_jobs', sa.Column('sql_nodes_total', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('document_jobs', sa.Column('sql_nodes_completed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('document_jobs', sa.Column('graph_nodes_total', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('document_jobs', sa.Column('graph_nodes_completed', sa.Integer(), nullable=False, server_default='0'))

    op.execute("""
        CREATE OR REPLACE FUNCTION notify_document_job_update()
        RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify(
                'document_status_updates',
                json_build_object(
                    'document_id', NEW.document_id,
                    'filename', NEW.filename,
                    'current_stage', NEW.current_stage,
                    'status', NEW.status,
                    'error_message', NEW.error_message,
                    'sql_mapped', NEW.sql_mapped,
                    'vector_mapped', NEW.vector_mapped,
                    'graph_mapped', NEW.graph_mapped,
                    'sql_nodes_total', NEW.sql_nodes_total,
                    'sql_nodes_completed', NEW.sql_nodes_completed,
                    'graph_nodes_total', NEW.graph_nodes_total,
                    'graph_nodes_completed', NEW.graph_nodes_completed,
                    'updated_at', NEW.updated_at
                )::text
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    op.drop_column('document_jobs', 'sql_nodes_total')
    op.drop_column('document_jobs', 'sql_nodes_completed')
    op.drop_column('document_jobs', 'graph_nodes_total')
    op.drop_column('document_jobs', 'graph_nodes_completed')

    op.execute("""
        CREATE OR REPLACE FUNCTION notify_document_job_update()
        RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify(
                'document_status_updates',
                json_build_object(
                    'document_id', NEW.document_id,
                    'filename', NEW.filename,
                    'current_stage', NEW.current_stage,
                    'status', NEW.status,
                    'error_message', NEW.error_message,
                    'sql_mapped', NEW.sql_mapped,
                    'vector_mapped', NEW.vector_mapped,
                    'graph_mapped', NEW.graph_mapped,
                    'updated_at', NEW.updated_at
                )::text
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
