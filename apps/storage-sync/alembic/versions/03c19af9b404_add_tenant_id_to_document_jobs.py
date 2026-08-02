"""add tenant_id to document_jobs

Revision ID: 03c19af9b404
Revises: 6b171d3bb1ee
Create Date: 2026-08-01 17:14:32.792170

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '03c19af9b404'
down_revision: Union[str, Sequence[str], None] = '6b171d3bb1ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('document_jobs', sa.Column('tenant_id', sa.String(length=255), nullable=False, server_default='default-tenant'))
    op.create_index(op.f('ix_document_jobs_tenant_id'), 'document_jobs', ['tenant_id'], unique=False)
    
    op.execute("""
        CREATE OR REPLACE FUNCTION notify_document_job_update()
        RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify(
                'document_status_updates',
                json_build_object(
                    'document_id', NEW.document_id,
                    'tenant_id', NEW.tenant_id,
                    'filename', NEW.filename,
                    'current_stage', NEW.current_stage,
                    'status', NEW.status,
                    'error_message', NEW.error_message,
                    'updated_at', NEW.updated_at
                )::text
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
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
                    'updated_at', NEW.updated_at
                )::text
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.drop_index(op.f('ix_document_jobs_tenant_id'), table_name='document_jobs')
    op.drop_column('document_jobs', 'tenant_id')
