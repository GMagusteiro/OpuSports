"""
telegram_bot.py
----------------
Bot do Telegram para entrega de alertas de value betting e comandos de
gestão. Usa python-telegram-bot (v20+, API assíncrona).

Comandos implementados:
  /start      - mensagem de boas-vindas
  /status     - mostra jogos atualmente monitorizados
  /config     - ajusta parâmetros (ex.: limiar de EV)
  /historico  - consulta os últimos alertas enviados

Para criar o bot:
  1. Fala com @BotFather no Telegram
  2. /newbot -> escolhe nome e username
  3. Copia o token para TELEGRAM_BOT_TOKEN no .env
  4. Envia uma mensagem qualquer ao bot e usa /getUpdates na API para
     obteres o teu chat_id, ou usa @userinfobot
"""

import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import settings
from db import get_conn
from value_finder import ValueSignal

logger = logging.getLogger("opusports.telegram_bot")

# Estado runtime simples e partilhado (poderia ser movido para bot_config na DB)
RUNTIME_STATE = {
    "ev_threshold": settings.EV_THRESHOLD,
}


def format_alert_message(
    signal: ValueSignal,
    competition: str,
    home_team: str,
    away_team: str,
    minute: int | None = None,
    extra_stats: str | None = None,
) -> str:
    """Formata um alerta seguindo a estrutura pedida: emoji + secções."""
    when = f"⏱️ Minuto {minute}'" if minute is not None else "⏱️ Pré-jogo"
    lines = [
        f"🏆 <b>{competition}</b>",
        f"⚽ {home_team} vs {away_team}",
        when,
        "",
        f"📊 Mercado: <b>{signal.market}</b> — {signal.selection}",
    ]
    if extra_stats:
        lines.append(f"📈 Estatísticas: {extra_stats}")

    lines += [
        "",
        f"💰 Odd: <b>{signal.odd:.2f}</b>",
        f"🎯 Prob. modelo: {signal.model_probability * 100:.1f}%",
        f"🏦 Prob. implícita (casa): {signal.implied_probability * 100:.1f}%",
        f"📈 Valor Esperado (EV): <b>+{signal.expected_value * 100:.1f}%</b>",
        "",
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "⚠️ <i>Não é aconselhamento financeiro. Aposta com responsabilidade.</i>",
    ]
    return "\n".join(lines)


async def send_alert(app: Application, message: str) -> None:
    """Envia uma mensagem de alerta formatada para o chat configurado."""
    try:
        await app.bot.send_message(
            chat_id=settings.TELEGRAM_CHAT_ID,
            text=message,
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Falha ao enviar alerta para o Telegram")


# ---------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 Bem-vindo ao <b>OpuSports Alert Bot</b>!\n\n"
        "Vou avisar-te quando detetar oportunidades de <i>value betting</i> "
        "em futebol, com base num modelo estatístico próprio.\n\n"
        "Comandos disponíveis:\n"
        "/status — jogos monitorizados agora\n"
        "/config — ver/ajustar parâmetros\n"
        "/historico — últimos alertas enviados\n\n"
        "⚠️ Este bot é uma ferramenta educativa/experimental. Não constitui "
        "aconselhamento financeiro nem garante lucro. Aposta apenas o que "
        "podes perder."
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT fixture_id, home_team, away_team, minute, status, home_goals, away_goals "
            "FROM fixtures WHERE status IN ('1H','2H','HT','ET') "
            "ORDER BY updated_at DESC LIMIT 15"
        ).fetchall()

    if not rows:
        await update.message.reply_text("Nenhum jogo ao vivo a ser monitorizado neste momento.")
        return

    lines = ["📡 <b>Jogos monitorizados:</b>\n"]
    for r in rows:
        home_goals = r["home_goals"] if r["home_goals"] is not None else "-"
        away_goals = r["away_goals"] if r["away_goals"] is not None else "-"
        lines.append(f"• {r['home_team']} {home_goals} - {away_goals} {r['away_team']} ({r['minute']}')")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text(
            f"⚙️ Configuração atual:\nLimiar de EV: {RUNTIME_STATE['ev_threshold'] * 100:.1f}%\n\n"
            "Para alterar: /config ev 0.07  (define o limiar para 7%)"
        )
        return

    if len(args) == 2 and args[0].lower() == "ev":
        try:
            new_threshold = float(args[1])
            if not (0 <= new_threshold <= 1):
                raise ValueError
            RUNTIME_STATE["ev_threshold"] = new_threshold
            await update.message.reply_text(f"✅ Limiar de EV atualizado para {new_threshold * 100:.1f}%")
        except ValueError:
            await update.message.reply_text("❌ Valor inválido. Usa um número entre 0 e 1, ex.: 0.05")
    else:
        await update.message.reply_text("Uso: /config ev <valor entre 0 e 1>")


async def cmd_historico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.market, a.selection, a.odd, a.expected_value, a.sent_at, "
            "       f.home_team, f.away_team "
            "FROM alerts a JOIN fixtures f ON f.fixture_id = a.fixture_id "
            "ORDER BY a.sent_at DESC LIMIT 10"
        ).fetchall()

    if not rows:
        await update.message.reply_text("Ainda não há alertas registados.")
        return

    lines = ["📜 <b>Últimos alertas:</b>\n"]
    for r in rows:
        lines.append(
            f"• {r['home_team']} vs {r['away_team']} — {r['market']} ({r['selection']})\n"
            f"  Odd {r['odd']:.2f} | EV +{r['expected_value'] * 100:.1f}% | {r['sent_at'][:16]}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


def build_application() -> Application:
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("historico", cmd_historico))
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    application = build_application()
    logger.info("Bot do Telegram a arrancar (polling)...")
    application.run_polling()
