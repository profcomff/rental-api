"""rental_session_deadline_ts

Revision ID: 4c4c8273d8c5
Revises: 498e4ee72e00
Create Date: 2025-09-25 13:06:06.539667

"""

from alembic import op
import sqlalchemy as sa


revision = '4c4c8273d8c5'
down_revision = 'fccbec47bef3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'rental_session',
        sa.Column(
            'deadline_ts', sa.DateTime(), server_default=sa.text("CURRENT_DATE + interval '16 hours'"), nullable=False
        ),
    )


def downgrade():
    op.drop_column('rental_session', 'deadline_ts')
