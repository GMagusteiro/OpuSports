# ⚽ OpuSports — Bot de Alertas de Value Betting para Futebol

Sistema automatizado que monitoriza jogos de futebol (pré-jogo e ao vivo),
estima probabilidades de eventos específicos com um modelo de machine
learning, compara-as com as odds das casas de apostas e envia alertas de
**value betting** via Telegram quando encontra uma vantagem estatística.

> ⚠️ **Aviso importante:** este projeto é um exercício técnico e educativo.
> Lê a secção [Riscos e Limitações](#-riscos-e-limitações-legaiséticas) antes
> de usares com dinheiro real.

---

## 📁 Estrutura do projeto

```
opusports/
├── main.py              # Script principal — orquestra todo o ciclo
├── config.py             # Configuração central (lê variáveis de ambiente)
├── db.py                  # Camada de acesso a SQLite
├── data_collector.py      # Integração com API-FOOTBALL
├── model_trainer.py       # Treino dos modelos preditivos (RandomForest)
├── value_finder.py        # Lógica de value betting (EV, overround)
├── telegram_bot.py        # Bot e comandos do Telegram
├── dashboard.py            # Dashboard opcional (Streamlit)
├── requirements.txt
├── .env.example            # Template de variáveis de ambiente
├── .gitignore
├── tests/
│   └── test_value_finder.py
├── data/                    # Base de dados SQLite (gerada em runtime)
├── logs/                    # Logs rotativos
└── docs/                    # Página estática (GitHub Pages)
```

---

## 🚀 Guia de instalação e configuração

### 1. Pré-requisitos
- Python 3.9+
- Conta na [API-FOOTBALL](https://www.api-football.com/) (existe plano gratuito limitado)
- Bot do Telegram criado via [@BotFather](https://t.me/BotFather)

### 2. Clonar e instalar dependências

```bash
git clone https://github.com/<o-teu-user>/opusports.git
cd opusports
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edita o `.env` e preenche:

| Variável | Onde obter |
|---|---|
| `API_FOOTBALL_KEY` | Dashboard da API-FOOTBALL após registo |
| `TELEGRAM_BOT_TOKEN` | Conversa com @BotFather → `/newbot` |
| `TELEGRAM_CHAT_ID` | Envia uma mensagem ao bot e consulta `/getUpdates`, ou usa @userinfobot |

### 4. Inicializar a base de dados

```bash
python db.py
```

### 5. Treinar o modelo (dados sintéticos, para demonstração)

```bash
python model_trainer.py
```

Isto gera os ficheiros `.joblib` em `models/`. **Estes modelos são treinados
com dados sintéticos e servem apenas para validar o pipeline** — ver secção
seguinte para treinar com dados reais.

### 6. Correr o bot

```bash
python main.py
```

O bot vai iniciar o polling ao Telegram e, num loop, recolher dados,
calcular probabilidades e enviar alertas quando `EV > EV_THRESHOLD`.

### 7. (Opcional) Dashboard

```bash
streamlit run dashboard.py
```

---

## 🎓 Como treinar o modelo com dados reais no futuro

O `model_trainer.py` está desenhado para que a transição seja simples:

1. **Recolhe histórico real:** corre `data_collector.py` periodicamente (ou
   em backfill, se a tua subscrição da API permitir pedidos históricos) para
   ires preenchendo as tabelas `fixtures`, `fixture_stats` e `odds_snapshots`
   em `data/opusports.db`. Precisas de pelo menos algumas centenas de jogos
   por mercado para um treino minimamente robusto.
2. **Regista o resultado real de cada evento** (ex.: se houve mais de 9.5
   cantos no jogo) — vais precisar de adicionar colunas de "resultado real"
   às tabelas ou cruzar com o endpoint de estatísticas finais da API depois
   do jogo terminar.
3. **Substitui `generate_synthetic_dataset()`:** cria uma função equivalente
   que faça `SELECT` às tuas tabelas reais e construa um `DataFrame` com as
   mesmas colunas em `FEATURE_COLUMNS` + as colunas `target_*`.
4. **Chama `train_all_models(df=o_teu_dataframe)`** em vez de deixar `df=None`.
5. **Valida sempre com validação cruzada** (já implementada) e desconfia de
   AUCs muito altos (>0.95) em dados reais — normalmente indicam *data
   leakage* (ex.: usar estatísticas do jogo já terminado para prever o
   próprio jogo).
6. Considera recalibrar o modelo periodicamente (os dados de futebol mudam
   de época para época, novas equipas, novos treinadores, etc.).

---

## 💰 Custo estimado mensal

| Item | Estimativa |
|---|---|
| API-FOOTBALL — plano gratuito | 0 € (100 pedidos/dia, sem odds ao vivo) |
| API-FOOTBALL — plano "Pro" (odds incluídas) | ~30-40 €/mês (consulta preços atuais em api-football.com/pricing) |
| VPS pequeno (DigitalOcean/Hetzner, 1 vCPU/1-2GB RAM) | ~5-6 €/mês |
| **Total mínimo funcional (sem odds ao vivo)** | **~5-6 €/mês** |
| **Total com odds ao vivo e volume razoável** | **~35-50 €/mês** |

Os preços de APIs mudam com frequência — confirma sempre os valores atuais
antes de decidires.

---

## ⚠️ Riscos e Limitações (legais/éticos)

- **Apostar envolve risco real de perda de dinheiro.** Um EV positivo
  calculado por um modelo não garante lucro — é uma estimativa estatística
  sujeita a erro de modelo, dados incompletos e variância de curto prazo.
- **Não é aconselhamento financeiro.** Este software é uma ferramenta de
  apoio à decisão, não uma recomendação de aposta.
- **Legalidade:** apostas desportivas são regulamentadas de forma diferente
  em cada país/região. Confirma que é legal apostar na tua jurisdição e que
  a casa de apostas que usas está licenciada localmente.
- **Termos de serviço das casas de apostas:** muitas casas proíbem ou
  limitam contas que usam ferramentas automatizadas para identificar valor
  ("value betting" sistemático). Podes ter a conta limitada ("gubado") ou
  encerrada. Este bot **não coloca apostas automaticamente** — apenas
  alerta; ainda assim, o uso sistemático de alertas pode levar ao mesmo
  resultado.
- **Overfitting e falsa confiança:** um backtest com dados sintéticos ou
  históricos limitados pode parecer lucrativo e falhar completamente em
  produção. Nunca apostes dinheiro que não podes perder, e testa sempre
  primeiro com apostas simuladas ("paper trading").
- **Jogo responsável:** se sentires que a aposta está a deixar de ser
  recreativa/controlada, procura apoio (em Portugal: [SICAD](https://www.sicad.pt/)
  e linhas de apoio ao jogo responsável das próprias casas de apostas).

---

## 🧪 Testes

```bash
pytest tests/
```

## 🛠️ Stack

Python 3.9+, `requests`, `pandas`, `numpy`, `scikit-learn`, `python-telegram-bot`,
`schedule`, `python-dotenv`, `joblib`, `streamlit` (dashboard opcional).

## 📄 Licença

Este projeto é fornecido "tal como está", para fins educativos, sem
qualquer garantia. Usa por tua conta e risco.
