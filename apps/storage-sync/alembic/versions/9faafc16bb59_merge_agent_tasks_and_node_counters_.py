"""merge agent_tasks and node_counters heads

Revision ID: 9faafc16bb59
Revises: b7c8d9e0f1a2, f2c3b4a5e6d7
Create Date: 2026-08-02 14:07:46.590970

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9faafc16bb59'
down_revision: Union[str, Sequence[str], None] = ('b7c8d9e0f1a2', 'f2c3b4a5e6d7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
