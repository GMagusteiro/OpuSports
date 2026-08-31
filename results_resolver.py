"""
results_resolver.py
--------------------
Resolve automaticamente o resultado ("ganhou" / "perdeu") dos alertas
pendentes, consultando o resultado final de cada jogo já terminado.

Sem isto, a coluna `alerts.result` fica sempre em "pendente" e o dashboard
não consegue calcular taxa de acerto nem P/L real — este script é o que
fecha esse ciclo.

Cobertura atual:
  - Mercado de CANTOS ("Mais de X Cantos"): resolvido automaticamente,
    com base nas estatísticas finais do jogo obtidas da API.
  - Mercado "golos na 2ª parte": resolvido automaticamente a partir do
    placar ao intervalo (guardado em fixtures.home_goals_ht/away_goals_ht)
    vs. placar final — só funciona para jogos monitorizados a partir de
    agora, já que o placar ao intervalo tem de ter sido capturado ao vivo.
  - Mercado "Próximo Golo": NÃO é resolvido aqui (exige seguir o timeline
    de golos minuto a minuto, que ainda não é guardado) — fica pendente
    para resolução manual ou implementação futura.

Uso recomendado: corre periodicamente (ex.: a cada 30 min) via cron ou
`schedule`, separado do processo principal do bot:

    python results_resolver.py
"""

import logging
import re

from data_collector import FootballDataClient, save_fixture, save_fixture_statistics
from db import get_conn, init_db

logger = logging.getLogger("opusports.results_resolver")

_LINE_RE = re.compile(r"(\d+(?:\.\d+)?)")

FINISHED_STATUSES = ("FT", "AET", "PEN")


def _extract_line(*texts: str | None) -> float | None:
    """Extrai o primeiro número (ex.: 9.5) de um conjunto de strings."""
    for text in texts:
        if not text:
            continue
        match = _LINE_RE.search(text)
        if match:
            return float(match.group(1))
    return None


def _refresh_fixture_and_stats(client: FootballDataClient, fixture_id: int) -> None:
    """Vai buscar à API o estado final do jogo e das estatísticas, e
    atualiza a base de dados local antes de tentar resolver alertas."""
    fixture_payload = client.get_fixture_by_id(fixture_id)
    if fixture_payload:
        save_fixture(fixture_payload)

    stats = client.get_fixture_statistics(fixture_id)
    if stats:
        save_fixture_statistics(fixture_id, stats, minute=90)


def _final_corners(fixture_id: int) -> int | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT home_corners, away_corners FROM fixture_stats "
            "WHERE fixture_id = ? AND home_corners IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (fixture_id,),
        ).fetchone()
    if row is None:
        return None
    return (row["home_corners"] or 0) + (row["away_corners"] or 0)


def resolve_corners_alert(alert_row) -> str | None:
    line = _extract_line(alert_row["market"], alert_row["selection"])
    total_corners = _final_corners(alert_row["fixture_id"])
    if line is None or total_corners is None:
        return None

    if total_corners == line:
        return None  # "push" — não deveria acontecer com linhas .5

    is_under = "under" in (alert_row["selection"] or "").lower() or \
               "menos" in (alert_row["selection"] or "").lower()
    covered = total_corners > line
    won = (not covered) if is_under else covered
    return "ganhou" if won else "perdeu"


def resolve_second_half_goals_alert(alert_row) -> str | None:
    with get_conn() as conn:
        fixture = conn.execute(
            "SELECT home_goals, away_goals, home_goals_ht, away_goals_ht "
            "FROM fixtures WHERE fixture_id = ?",
            (alert_row["fixture_id"],),
        ).fetchone()

    if fixture is None:
        return None
    if any(v is None for v in (fixture["home_goals"], fixture["away_goals"],
                                fixture["home_goals_ht"], fixture["away_goals_ht"])):
        return None  # placar ao intervalo não foi capturado — não dá para resolver

    goals_2nd_half = (
        (fixture["home_goals"] - fixture["home_goals_ht"]) +
        (fixture["away_goals"] - fixture["away_goals_ht"])
    )
    line = _extract_line(alert_row["market"], alert_row["selection"]) or 0.5
    return "ganhou" if goals_2nd_half > line else "perdeu"


def resolve_pending_alerts(client: FootballDataClient) -> int:
    """Percorre alertas pendentes de jogos terminados e tenta resolvê-los.

    Devolve o número de alertas resolvidos nesta execução.
    """
    with get_conn() as conn:
        pending = conn.execute(
            """
            SELECT a.id, a.fixture_id, a.market, a.selection, f.status
            FROM alerts a JOIN fixtures f ON f.fixture_id = a.fixture_id
            WHERE a.result = 'pendente'
            """
        ).fetchall()

    # Agrupa por fixture (evita pedir a mesma info repetidamente à API)
    fixture_ids_to_refresh = {row["fixture_id"] for row in pending}

    for fixture_id in fixture_ids_to_refresh:
        try:
            _refresh_fixture_and_stats(client, fixture_id)
        except Exception:
            logger.exception("Falha ao atualizar fixture %s", fixture_id)

    with get_conn() as conn:
        pending = conn.execute(
            """
            SELECT a.id, a.fixture_id, a.market, a.selection, f.status
            FROM alerts a JOIN fixtures f ON f.fixture_id = a.fixture_id
            WHERE a.result = 'pendente' AND f.status IN (?, ?, ?)
            """,
            FINISHED_STATUSES,
        ).fetchall()

    resolved_count = 0
    for alert in pending:
        market = (alert["market"] or "").lower()
        result = None

        if "canto" in market or "corner" in market:
            result = resolve_corners_alert(alert)
        elif "2ª parte" in market or "segunda parte" in market or "2nd half" in market:
            result = resolve_second_half_goals_alert(alert)
        # "Próximo Golo" fica de fora — ver docstring do módulo

        if result is not None:
            with get_conn() as conn:
                conn.execute("UPDATE alerts SET result = ? WHERE id = ?", (result, alert["id"]))
            resolved_count += 1
            logger.info("Alerta %s resolvido automaticamente: %s", alert["id"], result)

    return resolved_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    client = FootballDataClient()
    n = resolve_pending_alerts(client)
    print(f"{n} alerta(s) resolvido(s) nesta execução.")
