"""
db.py
-----
Camada de acesso a dados em SQLite. Guarda jogos, estatísticas, odds e
o histórico de alertas para permitir treino futuro do modelo e auditoria
de performance.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS fixtures (
    fixture_id INTEGER PRIMARY KEY,
    league_id INTEGER,
    league_name TEXT,
    home_team TEXT,
    away_team TEXT,
    kickoff_utc TEXT,
    status TEXT,
    minute INTEGER,
    home_goals INTEGER,
    away_goals INTEGER,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS fixture_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fixture_id INTEGER,
    minute INTEGER,
    home_xg REAL,
    away_xg REAL,
    home_shots_on_target INTEGER,
    away_shots_on_target INTEGER,
    home_corners INTEGER,
    away_corners INTEGER,
    home_possession REAL,
    away_possession REAL,
    captured_at TEXT,
    FOREIGN KEY (fixture_id) REFERENCES fixtures (fixture_id)
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fixture_id INTEGER,
    bookmaker TEXT,
    market TEXT,
    selection TEXT,
    line REAL,
    odd REAL,
    captured_at TEXT,
    FOREIGN KEY (fixture_id) REFERENCES fixtures (fixture_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fixture_id INTEGER,
    market TEXT,
    selection TEXT,
    model_probability REAL,
    implied_probability REAL,
    odd REAL,
    expected_value REAL,
    sent_at TEXT,
    result TEXT DEFAULT 'pendente',
    FOREIGN KEY (fixture_id) REFERENCES fixtures (fixture_id)
);

CREATE TABLE IF NOT EXISTS bot_config (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def init_db(db_path: str = None) -> None:
    """Cria as tabelas se ainda não existirem."""
    path = db_path or settings.DB_PATH
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_conn(db_path: str = None) -> Iterator[sqlite3.Connection]:
    path = db_path or settings.DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.utcnow().isoformat()


if __name__ == "__main__":
    init_db()
    print(f"Base de dados inicializada em: {settings.DB_PATH}")
