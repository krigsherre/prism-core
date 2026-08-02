"""Add document_jobs and notify trigger

Revision ID: 6b171d3bb1ee
Revises: 
Create Date: 2026-08-01 11:13:50.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '6b171d3bb1ee'
down_revision: Union[str, None] = '9df258918886'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'document_jobs',
        sa.Column('document_id', sa.String(255), primary_key=True),
        sa.Column('filename', sa.String(512), nullable=False),
        sa.Column('current_stage', sa.String(100), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
    )

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

    op.execute("""
        CREATE TRIGGER trigger_document_job_update
        AFTER INSERT OR UPDATE ON document_jobs
        FOR EACH ROW
        EXECUTE FUNCTION notify_document_job_update();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trigger_document_job_update ON document_jobs")
    op.execute("DROP FUNCTION IF EXISTS notify_document_job_update()")
    op.drop_table('document_jobs')
