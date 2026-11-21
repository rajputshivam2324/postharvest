"""Enable pgvector and convert nullable evidence embeddings, without changing raw readings."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(
            "ALTER TABLE evidence_chunks ALTER COLUMN embedding TYPE vector(768) "
            "USING CASE WHEN embedding IS NULL THEN NULL ELSE embedding::text::vector END"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE evidence_chunks ALTER COLUMN embedding TYPE json "
            "USING CASE WHEN embedding IS NULL THEN NULL ELSE embedding::text::json END"
        )
    # Never drop a shared database extension on application downgrade.
