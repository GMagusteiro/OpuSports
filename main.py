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


# Cada entrada liga um modelo treinado a um mercado de odds real.
# `odds_match`: função que decide se o nome de um mercado da API corresponde
# a este mercado — importante NÃO ser demasiado permissivo aqui, ou
# acabamos a comparar a probabilidade de um mercado (ex.: golos na 2ª parte)
# com a odd de outro completamente diferente (ex.: golos do jogo todo),
# o que invalida o cálculo do EV.
MARKET_CONFIGS = [
    {
        "model_name": "over_95_corners",
        "display_market": "Mais de 9.5 Cantos",
        "odds_match": lambda market: "corner" in market.lower(),
    },
    {
        "model_name": "over_05_2nd_half",
        "display_market": "Mais de 0.5 Golos (a qualquer momento)",
        # Aceita qualquer mercado de golos do jogo (não só 2ª parte), porque
        # é isso que normalmente está disponível nas odds ao vivo.
        #
        # AVISO: o modelo "over_05_2nd_half" foi treinado especificamente
        # para prever golos NA 2ª PARTE, não golos em qualquer momento do
        # jogo — por isso, ao comparar com odds de "golos a qualquer
        # momento", a probabilidade usada é uma aproximação, não um cálculo
        # rigoroso. Serve para o teste de hoje (validar o encanamento), mas
        # antes de dares mais peso a estes alertas específicos, treina um
        # modelo dedicado a "próximo golo / qualquer golo" na Fase 3.
        "odds_match": lambda market: "goal" in market.lower(),
    },
]


async def process_fixture(app, fixture_id: int) -> None:
    features = build_features_for_fixture(fixture_id)
    if features is None:
        return

    with get_conn() as conn:
        fixture = conn.execute(
            "SELECT * FROM fixtures WHERE fixture_id = ?", (fixture_id,)
        ).fetchone()
        odds_rows = conn.execute(
            "SELECT * FROM odds_snapshots WHERE fixture_id = ? ORDER BY id DESC LIMIT 100",
            (fixture_id,),
        ).fetchall()

    if fixture is None or not odds_rows:
        return

    import pandas as pd
    X = pd.DataFrame([features])[FEATURE_COLUMNS]

    for cfg in MARKET_CONFIGS:
        try:
            model = load_model(cfg["model_name"])
            prob = model.predict_proba(X)[0][1]
        except FileNotFoundError:
            logger.warning("Modelo '%s' não encontrado — corre model_trainer.py primeiro", cfg["model_name"])
            continue

        # Agrupa odds por seleção mais recente para este mercado específico
        selections_odds = {}
        for r in odds_rows:
            if r["market"] and cfg["odds_match"](r["market"]):
                selections_odds[r["selection"]] = r["odd"]

        if not selections_odds:
            continue  # esta API/bookmaker não tem este mercado para este jogo agora

        model_probs = {sel: prob for sel in selections_odds}  # simplificação didática
        signals = evaluate_market(fixture_id, cfg["display_market"], selections_odds, model_probs)
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
        fixture_ids = collect_live_snapshot(client, team_names=settings.MONITORED_TEAM_NAMES)
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
        if settings.MONITORED_TEAM_NAMES:
            logger.info("Filtro de equipas ativo (modo de teste): %s", ", ".join(settings.MONITORED_TEAM_NAMES))
        else:
            logger.warning(
                "Sem filtro de equipas — o bot vai processar TODOS os jogos ao vivo do mundo. "
                "Isto pode esgotar rapidamente o limite diário de pedidos de planos gratuitos/baixos."
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
