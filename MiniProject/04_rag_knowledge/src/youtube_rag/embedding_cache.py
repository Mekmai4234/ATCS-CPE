"""Private prepared-text embeddings; successful entries are resumable checkpoints."""

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert

from .embeddings import validate_vectors
from .models import digest

cache_metadata = sa.MetaData()
embeddings = sa.Table(
    "rag04_embedding_cache",
    cache_metadata,
    sa.Column("cache_id", sa.String, primary_key=True),
    sa.Column("scope", sa.JSON, nullable=False),
    sa.Column("vector", sa.JSON, nullable=False),
)


class EmbeddingCache:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    def key(self, scope, prepared, purpose):
        return digest(
            {
                "format": 1,
                "scope": scope,
                "prepared": prepared,
                "purpose": purpose,
                "provider": self.settings.embedding_provider,
                "model": self.settings.embedding_model,
                "dimensions": self.settings.embedding_dimensions,
                "fingerprint": self.settings.fingerprint,
            }
        )

    def get(self, scope, prepared, purpose):
        with self.database.read() as c:
            value = c.scalar(
                sa.select(embeddings.c.vector).where(
                    embeddings.c.cache_id == self.key(scope, prepared, purpose)
                )
            )
        if value is None:
            return None
        return validate_vectors([value], 1, self.settings.embedding_dimensions)[0]

    def put(self, scope, prepared, purpose, vector):
        validate_vectors([vector], 1, self.settings.embedding_dimensions)
        with self.database.write() as c:
            c.execute(
                insert(embeddings)
                .values(cache_id=self.key(scope, prepared, purpose), scope=scope, vector=vector)
                .on_conflict_do_nothing()
            )

    @staticmethod
    def purge(c, video_id, generation):
        for row in c.execute(sa.select(embeddings)).mappings():
            if any(
                s["video_id"] == video_id and s["generation"] <= generation
                for s in row["scope"]["sources"]
            ):
                c.execute(embeddings.delete().where(embeddings.c.cache_id == row["cache_id"]))
