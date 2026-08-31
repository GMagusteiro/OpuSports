"""
dashboard.py
------------
Dashboard opcional em Streamlit para visualizar:
  - Alertas gerados
  - Performance do modelo (taxa de acerto, quando resultado for atualizado)
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

col1, col2, col3 = st.columns(3)
col1.metric("Total de alertas", len(alerts_df))

resolved = alerts_df[alerts_df["result"].isin(["ganhou", "perdeu"])]
if not resolved.empty:
    hit_rate = (resolved["result"] == "ganhou").mean() * 100
    col2.metric("Taxa de acerto (resolvidos)", f"{hit_rate:.1f}%")

    # Lucro/Perda simulado com stake fixo = 1 unidade
    resolved = resolved.copy()
    resolved["pnl"] = resolved.apply(
        lambda r: (r["odd"] - 1) if r["result"] == "ganhou" else -1, axis=1
    )
    total_pnl = resolved["pnl"].sum()
    col3.metric("P/L simulado (stake=1)", f"{total_pnl:+.2f} unidades")
else:
    col2.metric("Taxa de acerto (resolvidos)", "sem dados")
    col3.metric("P/L simulado", "sem dados")

st.subheader("Alertas recentes")
st.dataframe(alerts_df, use_container_width=True)

st.subheader("Distribuição de EV por mercado")
st.bar_chart(alerts_df.groupby("market")["expected_value"].mean())

st.caption(
    "⚠️ O 'result' de cada alerta tem de ser atualizado manualmente (ou por um "
    "job separado que consulta o resultado final do jogo) para os cálculos de "
    "taxa de acerto e P/L ficarem corretos."
)
