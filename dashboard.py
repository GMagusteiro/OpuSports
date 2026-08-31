"""
dashboard.py
------------
Dashboard opcional em Streamlit para visualizar:
  - Alertas gerados e odd média
  - Performance do modelo (taxa de acerto, calculada sobre alertas já
    resolvidos por `results_resolver.py`)
  - Lucro/Perda simulado (assumindo stake fixo de 1 unidade por alerta)

Corre com:  streamlit run dashboard.py
"""

import pandas as pd
import streamlit as st

from db import get_conn

st.set_page_config(page_title="OpuSports Dashboard", page_icon="⚽", layout="wide")
st.title("⚽ OpuSports — Dashboard de Alertas")

with get_conn() as conn:
    alerts_df = pd.read_sql_query(
        """
        SELECT a.id, a.market, a.selection, a.odd, a.expected_value, a.sent_at, a.result,
               f.home_team, f.away_team, f.league_name
        FROM alerts a JOIN fixtures f ON f.fixture_id = a.fixture_id
        ORDER BY a.sent_at DESC
        """,
        conn,
    )

if alerts_df.empty:
    st.info("Ainda não há alertas registados. Corre `python main.py` para começar a gerar dados.")
    st.stop()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total de alertas", len(alerts_df))
col2.metric("Odd média", f"{alerts_df['odd'].mean():.2f}")

resolved = alerts_df[alerts_df["result"].isin(["ganhou", "perdeu"])]
pending_count = len(alerts_df) - len(resolved)

if not resolved.empty:
    hit_rate = (resolved["result"] == "ganhou").mean() * 100
    col3.metric(
        "Taxa de acerto",
        f"{hit_rate:.1f}%",
        help=f"{len(resolved)} resolvido(s) de {len(alerts_df)} total ({pending_count} pendente(s))",
    )

    # Lucro/Perda simulado com stake fixo = 1 unidade
    resolved = resolved.copy()
    resolved["pnl"] = resolved.apply(
        lambda r: (r["odd"] - 1) if r["result"] == "ganhou" else -1, axis=1
    )
    total_pnl = resolved["pnl"].sum()
    col4.metric("P/L simulado (stake=1)", f"{total_pnl:+.2f} unidades")

    st.caption(
        f"Odd média dos alertas **resolvidos que ganharam**: "
        f"{resolved[resolved['result'] == 'ganhou']['odd'].mean():.2f}" if (resolved["result"] == "ganhou").any() else ""
    )
else:
    col3.metric("Taxa de acerto", "sem dados")
    col4.metric("P/L simulado", "sem dados")

st.subheader("Alertas recentes")
st.dataframe(alerts_df, use_container_width=True)

st.subheader("Distribuição de EV por mercado")
st.bar_chart(alerts_df.groupby("market")["expected_value"].mean())

st.caption(
    "⚠️ Os alertas de cantos e de golos na 2ª parte são resolvidos automaticamente "
    "por `results_resolver.py` (corre-o periodicamente, ex.: a cada 30 min). "
    "Alertas do mercado 'Próximo Golo' ainda ficam pendentes e precisam de "
    "resolução manual — ver limitações no topo do ficheiro."
)
