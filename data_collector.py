"""
data_collector.py
------------------
Responsável por comunicar com a API de futebol (API-FOOTBALL) e obter:
  - Jogos ao vivo com estatísticas (remates, cantos, posse de bola, xG)
  - Histórico de confrontos diretos
  - Forma recente das equipas
  - Odds em tempo real

Todas as chamadas passam por um rate limiter simples para não exceder o
plano contratado da API. Os dados são guardados em SQLite para permitir
treino futuro do modelo com dados reais.

NOTA IMPORTANTE:
A API-FOOTBALL tem um plano gratuito limitado (100 pedidos/dia) e as odds
ao vivo normalmente só estão disponíveis em planos pagos. Consulta
https://www.api-football.com/pricing para os detalhes atualizados.
"""

import logging
import time
from collections import deque
from typing import Any, Optional

import requests

from config import settings
from db import get_conn, now_iso

logger = logging.getLogger("opusports.data_collector")


class RateLimiter:
    """Limita o número de pedidos por minuto usando uma janela deslizante."""

    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self._timestamps: deque = deque()

    def wait_if_needed(self) -> None:
        now = time.time()
        while self._timestamps and now - self._timestamps[0] > 60:
            self._timestamps.popleft()
        if len(self._timestamps) >= self.max_per_minute:
            sleep_for = 60 - (now - self._timestamps[0])
            if sleep_for > 0:
                logger.debug("Rate limit atingido, a aguardar %.1fs", sleep_for)
                time.sleep(sleep_for)
        self._timestamps.append(time.time())


class FootballDataClient:
    """Cliente fino sobre a API-FOOTBALL (v3)."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or settings.API_FOOTBALL_KEY
        self.base_url = base_url or settings.API_FOOTBALL_BASE_URL
        self.session = requests.Session()
        self.session.headers.update({"x-apisports-key": self.api_key})
        self.rate_limiter = RateLimiter(settings.MAX_REQUESTS_PER_MINUTE)

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.rate_limiter.wait_if_needed()
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            resp = self.session.get(url, params=params or {}, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("errors"):
                logger.warning("API devolveu erros para %s: %s", endpoint, payload["errors"])
            return payload
        except requests.exceptions.RequestException as exc:
            logger.error("Falha ao chamar %s: %s", endpoint, exc)
            return {"response": [], "errors": [str(exc)]}

    # ---- Jogos ----
    def get_live_fixtures(self) -> list[dict[str, Any]]:
        """Devolve todos os jogos atualmente ao vivo."""
        data = self._get("fixtures", {"live": "all"})
        return data.get("response", [])

    def get_fixtures_today(self, date_str: str) -> list[dict[str, Any]]:
        """Jogos agendados para uma data (YYYY-MM-DD), incluindo pré-jogo."""
        data = self._get("fixtures", {"date": date_str})
        return data.get("response", [])

    def get_fixture_by_id(self, fixture_id: int) -> dict[str, Any] | None:
        """Devolve o payload completo de um jogo específico (útil para
        confirmar o estado final depois de terminar)."""
        data = self._get("fixtures", {"id": fixture_id})
        response = data.get("response", [])
        return response[0] if response else None

    def get_fixture_statistics(self, fixture_id: int) -> list[dict[str, Any]]:
        data = self._get("fixtures/statistics", {"fixture": fixture_id})
        return data.get("response", [])

    def get_head_to_head(self, team1_id: int, team2_id: int, last: int = 10) -> list[dict[str, Any]]:
        data = self._get("fixtures/headtohead", {"h2h": f"{team1_id}-{team2_id}", "last": last})
        return data.get("response", [])

    def get_team_recent_form(self, team_id: int, league_id: int, season: int, last: int = 10) -> list[dict[str, Any]]:
        data = self._get(
            "fixtures",
            {"team": team_id, "league": league_id, "season": season, "last": last},
        )
        return data.get("response", [])

    # ---- Odds ----
    def get_odds_live(self, fixture_id: int) -> list[dict[str, Any]]:
        """Odds ao vivo (normalmente requer plano pago da API-FOOTBALL)."""
        data = self._get("odds/live", {"fixture": fixture_id})
        return data.get("response", [])

    def get_odds_pregame(self, fixture_id: int) -> list[dict[str, Any]]:
        data = self._get("odds", {"fixture": fixture_id})
        return data.get("response", [])


# ---------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------

def save_fixture(fixture_payload: dict[str, Any]) -> int:
    fixture = fixture_payload["fixture"]
    league = fixture_payload["league"]
    teams = fixture_payload["teams"]
    goals = fixture_payload.get("goals", {})
    # A API-FOOTBALL devolve o placar ao intervalo em "score.halftime" assim
    # que o intervalo acontece, independentemente do estado atual do jogo —
    # é o que nos permite mais tarde resolver o mercado "golos na 2ª parte".
    halftime = fixture_payload.get("score", {}).get("halftime", {}) or {}

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO fixtures (fixture_id, league_id, league_name, home_team, away_team,
                                   kickoff_utc, status, minute, home_goals, away_goals,
                                   home_goals_ht, away_goals_ht, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fixture_id) DO UPDATE SET
                status=excluded.status,
                minute=excluded.minute,
                home_goals=excluded.home_goals,
                away_goals=excluded.away_goals,
                home_goals_ht=COALESCE(excluded.home_goals_ht, fixtures.home_goals_ht),
                away_goals_ht=COALESCE(excluded.away_goals_ht, fixtures.away_goals_ht),
                updated_at=excluded.updated_at
            """,
            (
                fixture["id"],
                league["id"],
                league["name"],
                teams["home"]["name"],
                teams["away"]["name"],
                fixture["date"],
                fixture["status"]["short"],
                fixture["status"].get("elapsed"),
                goals.get("home"),
                goals.get("away"),
                halftime.get("home"),
                halftime.get("away"),
                now_iso(),
            ),
        )
    return fixture["id"]


def save_fixture_statistics(fixture_id: int, stats_payload: list[dict[str, Any]], minute: Optional[int] = None) -> None:
    """Extrai estatísticas relevantes (remates, cantos, posse) da resposta da API."""
    if len(stats_payload) < 2:
        return

    def extract(team_stats: dict[str, Any], stat_type: str) -> Any:
        for item in team_stats.get("statistics", []):
            if item["type"] == stat_type:
                return item["value"]
        return None

    home_stats, away_stats = stats_payload[0], stats_payload[1]

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO fixture_stats (fixture_id, minute, home_xg, away_xg,
                                        home_shots_on_target, away_shots_on_target,
                                        home_corners, away_corners,
                                        home_possession, away_possession, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fixture_id,
                minute,
                extract(home_stats, "expected_goals"),
                extract(away_stats, "expected_goals"),
                extract(home_stats, "Shots on Goal"),
                extract(away_stats, "Shots on Goal"),
                extract(home_stats, "Corner Kicks"),
                extract(away_stats, "Corner Kicks"),
                extract(home_stats, "Ball Possession"),
                extract(away_stats, "Ball Possession"),
                now_iso(),
            ),
        )


def save_odds(fixture_id: int, odds_payload: list[dict[str, Any]]) -> None:
    with get_conn() as conn:
        for entry in odds_payload:
            for bookmaker in entry.get("bookmakers", []):
                for bet in bookmaker.get("bets", []):
                    for value in bet.get("values", []):
                        conn.execute(
                            """
                            INSERT INTO odds_snapshots (fixture_id, bookmaker, market, selection,
                                                         line, odd, captured_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                fixture_id,
                                bookmaker.get("name"),
                                bet.get("name"),
                                value.get("value"),
                                None,
                                float(value.get("odd", 0)),
                                now_iso(),
                            ),
                        )


def collect_live_snapshot(client: FootballDataClient) -> list[int]:
    """Faz uma ronda completa de recolha para todos os jogos ao vivo.

    Devolve a lista de fixture_ids processados nesta ronda.
    """
    fixture_ids: list[int] = []
    live_fixtures = client.get_live_fixtures()
    logger.info("Jogos ao vivo encontrados: %d", len(live_fixtures))

    for fixture_payload in live_fixtures:
        fixture_id = save_fixture(fixture_payload)
        fixture_ids.append(fixture_id)

        minute = fixture_payload["fixture"]["status"].get("elapsed")
        stats = client.get_fixture_statistics(fixture_id)
        save_fixture_statistics(fixture_id, stats, minute=minute)

        odds = client.get_odds_live(fixture_id)
        if odds:
            save_odds(fixture_id, odds)

    return fixture_ids


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from db import init_db

    init_db()
    client = FootballDataClient()
    ids = collect_live_snapshot(client)
    print(f"Snapshot recolhido para {len(ids)} jogo(s).")
