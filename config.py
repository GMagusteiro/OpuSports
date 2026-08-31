"""
config.py
---------
Configuração central do OpuSports Bot.

Todas as chaves de API e parâmetros sensíveis vêm de variáveis de ambiente
(nunca hardcoded no código). Cria um ficheiro `.env` a partir de
`.env.example` e preenche os teus valores.

Uso:
    from config import settings
    settings.API_FOOTBALL_KEY
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Carrega variáveis de um ficheiro .env se existir (não falha se não existir)
load_dotenv()


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    # --- API de dados de futebol ---
    API_FOOTBALL_KEY: str = os.getenv("API_FOOTBALL_KEY", "COLOCA_AQUI_A_TUA_CHAVE")
    API_FOOTBALL_BASE_URL: str = os.getenv(
        "API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io"
    )

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "COLOCA_AQUI_O_TEU_TOKEN")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "COLOCA_AQUI_O_TEU_CHAT_ID")

    # --- Parâmetros de negócio ---
    EV_THRESHOLD: float = _get_float("EV_THRESHOLD", 0.05)          # 5% de vantagem mínima
    POLL_INTERVAL_SECONDS: int = _get_int("POLL_INTERVAL_SECONDS", 45)
    MAX_REQUESTS_PER_MINUTE: int = _get_int("MAX_REQUESTS_PER_MINUTE", 25)

    # --- Ligas monitorizadas (IDs da API-FOOTBALL). Vazio = todas as suportadas ---
    MONITORED_LEAGUE_IDS: tuple = field(default_factory=lambda: tuple(
        int(x) for x in os.getenv("MONITORED_LEAGUE_IDS", "").split(",") if x.strip()
    ))

    # --- Caminhos locais ---
    DB_PATH: str = os.getenv("DB_PATH", "data/opusports.db")
    LOG_PATH: str = os.getenv("LOG_PATH", "logs/opusports.log")
    MODEL_DIR: str = os.getenv("MODEL_DIR", "models")


settings = Settings()
