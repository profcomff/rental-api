"""add-session-id

Revision ID: 498e4ee72e00
Revises: c00918b76464
Create Date: 2025-03-02 16:14:30.619629

"""

import sqlalchemy as sa
from alembic import op


revision = '498e4ee72e00'
down_revision = 'c00918b76464'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('strike', sa.Column('session_id', sa.Integer(), nullable=True))
    op.create_foreign_key('strike_session_id_fkey', 'strike', 'rental_session', ['session_id'], ['id'])


def downgrade():
    op.drop_constraint('strike_session_id_fkey', 'strike', type_='foreignkey')
    op.drop_column('strike', 'session_id')
