"""Device pairing codes

Existing devices already hold a credential, so they count as paired from the day they were
registered. No reading, batch or assignment is touched.
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.add_column(sa.Column("paired_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE devices SET paired_at = created_at")
    op.create_table(
        "pairing_codes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_pairing_codes_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], name=op.f("fk_pairing_codes_device_id_devices")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pairing_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_pairing_codes_code_hash")),
    )
    op.create_index("ix_pairing_device", "pairing_codes", ["device_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pairing_device", table_name="pairing_codes")
    op.drop_table("pairing_codes")
    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_column("paired_at")
