"""add-session-id

Revision ID: 498e4ee72e00
Revises: c00918b76464
Create Date: 2025-03-02 16:14:30.619629

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '498e4ee72e00'
down_revision = 'c00918b76464'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('strike', sa.Column('session_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'strike', 'rental_session', ['session_id'], ['id'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'strike', type_='foreignkey')
    op.drop_column('strike', 'session_id')
    # ### end Alembic commands ###
