import sys
from pathlib import Path

import pytest

# Permet d'importer app, db et volley depuis le dossier parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402


@pytest.fixture
def app(tmp_path):
    """Une application avec sa propre base de données temporaire pour chaque test."""
    return create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.db"),
        "AUJOURDHUI": "2026-10-23",
        "MOT_DE_PASSE_ADMIN": "secret",
    })


@pytest.fixture
def client(app):
    return app.test_client()
