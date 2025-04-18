"""initial

Revision ID: c00918b76464
Revises:
Create Date: 2025-03-02 15:44:18.126632

"""

import sqlalchemy as sa
from alembic import op


revision = 'c00918b76464'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'item_type',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('image_url', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'strike',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('create_ts', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'item',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('type_id', sa.Integer(), nullable=False),
        sa.Column('is_available', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ['type_id'],
            ['item_type.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'rental_session',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('admin_open_id', sa.Integer(), nullable=True),
        sa.Column('admin_close_id', sa.Integer(), nullable=True),
        sa.Column('reservation_ts', sa.DateTime(), nullable=False),
        sa.Column('start_ts', sa.DateTime(), nullable=True),
        sa.Column('end_ts', sa.DateTime(), nullable=True),
        sa.Column('actual_return_ts', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ['item_id'],
            ['item.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('admin_id', sa.Integer(), nullable=True),
        sa.Column('session_id', sa.Integer(), nullable=True),
        sa.Column('action_type', sa.String(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('create_ts', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['session_id'],
            ['rental_session.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('event')
    op.drop_table('rental_session')
    op.drop_table('item')
    op.drop_table('strike')
    op.drop_table('item_type')
