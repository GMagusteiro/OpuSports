"""
main.py
-------
Script principal do OpuSports Alert Bot.

Orquestra o ciclo completo:
  1. Recolhe dados de jogos ao vivo (data_collector)
  2. Para cada jogo, calcula probabilidades com o modelo treinado
  3. Compara com as odds (value_finder)
  4. Envia alertas via Telegram quando há valor
  5. Repete em loop com intervalo configurável (schedule)

Corre com:  python main.py
Para parar: Ctrl+C
"""

import asyncio
import logging
import logging.handlers
from pathlib import Path

import schedule

from config import settings
from data_collector import FootballDataClient, collect_live_snapshot
from db import get_conn, init_db, now_iso
from model_trainer import load_model, FEATURE_COLUMNS
from telegram_bot import build_application, format_alert_message, send_alert
from value_finder import evaluate_market, filter_valuable_signals

logger = logging.getLogger("opusports.main")


def setup_logging() -> None:
    Path(settings.LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        settings.LOG_PATH, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.addHandler(logging.StreamHandler())  # também imprime na consola


def build_features_for_fixture(fixture_id: int) -> dict | None:
    """Constrói o vetor de features mais recente para um jogo a partir da DB.

    Em produção isto deveria combinar múltiplas fontes (forma recente,
    H2H, etc.) — aqui usamos a última linha de fixture_stats como exemplo
    simplificado e educativo.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM fixture_stats WHERE fixture_id = ? ORDER BY id DESC LIMIT 1",
            (fixture_id,),
        ).fetchone()

    if row is None:
        return None

    # Placeholders para médias históricas (substituir por cálculo real com
    # base em get_team_recent_form quando disponível)
    features = {
        "home_avg_goals_scored": 1.4,
        "away_avg_goals_scored": 1.1,
        "home_avg_goals_conceded": 1.2,
        "away_avg_goals_conceded": 1.4,
        "home_avg_corners": row["home_corners"] or 5.0,
        "away_avg_corners": row["away_corners"] or 4.0,
        "match_xg_home": row["home_xg"] or 0.8,
        "match_xg_away": row["away_xg"] or 0.6,
        "minute": row["minute"] or 0,
        "home_possession": row["home_possession"] or 50.0,
        "away_possession": row["away_possession"] or 50.0,
        "home_shots_on_target": row["home_shots_on_target"] or 0,
        "away_shots_on_target": row["away_shots_on_target"] or 0,
    }
    return features


async def process_fixture(app, fixture_id: int) -> None:
    features = build_features_for_fixture(fixture_id)
    if features is None:
        return

    with get_conn() as conn:
        fixture = conn.execute(
            "SELECT * FROM fixtures WHERE fixture_id = ?", (fixture_id,)
        ).fetchone()
        odds_rows = conn.execute(
            "SELECT * FROM odds_snapshots WHERE fixture_id = ? ORDER BY id DESC LIMIT 20",
            (fixture_id,),
        ).fetchall()

    if fixture is None or not odds_rows:
        return

    import pandas as pd
    X = pd.DataFrame([features])[FEATURE_COLUMNS]

    try:
        model_corners = load_model("over_95_corners")
        prob_corners = model_corners.predict_proba(X)[0][1]
    except FileNotFoundError:
        logger.warning("Modelo 'over_95_corners' não encontrado — corre model_trainer.py primeiro")
        return

    # Agrupa odds por mercado/seleção mais recente (simplificado)
    selections_odds = {}
    for r in odds_rows:
        if r["market"] and "corner" in r["market"].lower():
            selections_odds[r["selection"]] = r["odd"]

    if not selections_odds:
        return

    model_probs = {sel: prob_corners for sel in selections_odds}  # simplificação didática
    signals = evaluate_market(fixture_id, "Mais de 9.5 Cantos", selections_odds, model_probs)
    valuable = filter_valuable_signals(signals)

    for signal in valuable:
        message = format_alert_message(
            signal,
            competition=fixture["league_name"],
            home_team=fixture["home_team"],
            away_team=fixture["away_team"],
            minute=fixture["minute"],
        )
        await send_alert(app, message)

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO alerts (fixture_id, market, selection, model_probability,
                                     implied_probability, odd, expected_value, sent_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fixture_id, signal.market, signal.selection, signal.model_probability,
                    signal.implied_probability, signal.odd, signal.expected_value, now_iso(),
                ),
            )


async def run_cycle(client: FootballDataClient, app) -> None:
    logger.info("A iniciar novo ciclo de recolha e análise...")
    try:
        fixture_ids = collect_live_snapshot(client)
    except Exception:
        logger.exception("Erro na recolha de dados — ciclo saltado")
        return

    for fixture_id in fixture_ids:
        try:
            await process_fixture(app, fixture_id)
        except Exception:
            logger.exception("Erro ao processar fixture %s", fixture_id)


async def main_async() -> None:
    setup_logging()
    init_db()

    client = FootballDataClient()
    app = build_application()

    async with app:
        await app.start()
        logger.info(
            "OpuSports Bot iniciado. Intervalo de polling: %ss | Limiar EV: %.1f%%",
            settings.POLL_INTERVAL_SECONDS, settings.EV_THRESHOLD * 100,
        )
        try:
            while True:
                await run_cycle(client, app)
                await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("A encerrar OpuSports Bot...")
        finally:
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main_async())
