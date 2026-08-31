"""
export_public_stats.py
-----------------------
Gera um ficheiro JSON com estatísticas agregadas e sem informação sensível,
para seres publicado em `docs/stats.json` e lido pela página estática do
GitHub Pages (docs/index.html).

IMPORTANTE — o que é (e não é) publicado:
  - Publica: totais, taxa de acerto, odd média, P/L simulado, e um histórico
    resumido dos últimos alertas RESOLVIDOS (mercado, odd, resultado, data).
  - NÃO publica: o teu EV_THRESHOLD, probabilidades do modelo, nem qualquer
    coisa que exponha a lógica interna de decisão — só o resultado final.
  - Só deves ligar isto ao site publicamente depois de teres semanas de
    histórico REAL (ver Fase 4 do plano de deployment). Publicar números
    vazios ou vindos de dados sintéticos passa a ideia errada.

Uso recomendado: corre depois do `results_resolver.py`, no mesmo cron job,
e faz commit+push do `docs/stats.json` para o repositório (ver exemplo de
crontab no fim deste ficheiro).

    python export_public_stats.py
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from db import get_conn

logger = logging.getLogger("opusports.export_public_stats")

OUTPUT_PATH = Path("docs/stats.json")
MAX_RECENT_ALERTS = 15


def build_public_stats() -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT a.market, a.odd, a.result, a.sent_at
            FROM alerts a
            ORDER BY a.sent_at DESC
            """
        ).fetchall()

    total_alerts = len(rows)
    resolved = [r for r in rows if r["result"] in ("ganhou", "perdeu")]
    wins = [r for r in resolved if r["result"] == "ganhou"]

    hit_rate = (len(wins) / len(resolved) * 100) if resolved else None
    avg_odd_all = sum(r["odd"] for r in rows) / total_alerts if total_alerts else None
    avg_odd_wins = sum(r["odd"] for r in wins) / len(wins) if wins else None

    pnl = sum((r["odd"] - 1) if r["result"] == "ganhou" else -1 for r in resolved) if resolved else None

    recent = [
        {
            "market": r["market"],
            "odd": round(r["odd"], 2),
            "result": r["result"],
            "date": r["sent_at"][:10],
        }
        for r in rows[:MAX_RECENT_ALERTS]
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_alerts": total_alerts,
        "resolved_alerts": len(resolved),
        "pending_alerts": total_alerts - len(resolved),
        "hit_rate_pct": round(hit_rate, 1) if hit_rate is not None else None,
        "avg_odd": round(avg_odd_all, 2) if avg_odd_all is not None else None,
        "avg_odd_wins": round(avg_odd_wins, 2) if avg_odd_wins is not None else None,
        "simulated_pnl_units": round(pnl, 2) if pnl is not None else None,
        "recent_alerts": recent,
    }


def export(output_path: Path = OUTPUT_PATH) -> dict:
    stats = build_public_stats()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Estatísticas públicas exportadas para %s", output_path)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    stats = export()
    print(json.dumps(stats, ensure_ascii=False, indent=2))

# ---------------------------------------------------------------------
# Exemplo de crontab no VPS (roda a cada 30 min, resolve alertas, exporta
# estatísticas, e publica no GitHub — precisa de um deploy key ou PAT
# configurado no repositório clonado no VPS):
#
#   */30 * * * * cd /home/opusports/OpuSports && \
#     source venv/bin/activate && \
#     python results_resolver.py && \
#     python export_public_stats.py && \
#     git add docs/stats.json && \
#     (git commit -m "chore: atualizar estatísticas públicas" -q || true) && \
#     git push -q origin main
#
# O "|| true" no commit evita que o cron falhe quando não há alterações
# (ex.: nenhum alerta novo resolvido desde a última execução).
# ---------------------------------------------------------------------
