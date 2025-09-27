"""deadline_ts_rental_session

Revision ID: fb8a57b65c4d
Revises: fccbec47bef3
Create Date: 2025-09-25 19:40:23.737319

"""

import sqlalchemy as sa
from alembic import op


revision = 'fb8a57b65c4d'
down_revision = 'fccbec47bef3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('rental_session', sa.Column('deadline_ts', sa.DateTime(), nullable=False))


def downgrade():
    op.drop_column('rental_session', 'deadline_ts')
