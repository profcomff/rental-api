"""add_user_phone_to_rental_session

Revision ID: fccbec47bef3
Revises: 498e4ee72e00
Create Date: 2025-09-20 23:26:37.267560

"""

import sqlalchemy as sa
from alembic import op


revision = 'fccbec47bef3'
down_revision = '498e4ee72e00'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('rental_session', sa.Column('user_phone', sa.String(), nullable=True))


def downgrade():
    op.drop_column('rental_session', 'user_phone')
