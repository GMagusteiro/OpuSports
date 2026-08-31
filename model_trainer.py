"""
model_trainer.py
-----------------
Treina modelos de classificação para prever probabilidades de eventos
específicos do jogo:
  - "Mais de 0.5 golos na 2ª parte"
  - "Próximo golo" por equipa (casa / fora / nenhum)
  - "Mais de X cantos" (linha configurável)

IMPORTANTE — DADOS SINTÉTICOS:
Este ficheiro gera dados sintéticos plausíveis apenas para que o pipeline
funcione de ponta a ponta e sirva de demonstração/educação. Um modelo
treinado com dados sintéticos NÃO deve ser usado para apostar dinheiro
real. Antes de usar em produção, substitui `generate_synthetic_dataset()`
por dados reais recolhidos via `data_collector.py` (ver secção "Treinar
com dados reais" no README).

Algoritmo: RandomForest (scikit-learn), por ser robusto, pouco sensível a
outliers e fácil de interpretar (feature_importances_). Fica comentado
como trocar para XGBoost.
"""

import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import brier_score_loss, classification_report, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split

from config import settings

logger = logging.getLogger("opusports.model_trainer")

FEATURE_COLUMNS = [
    "home_avg_goals_scored",
    "away_avg_goals_scored",
    "home_avg_goals_conceded",
    "away_avg_goals_conceded",
    "home_avg_corners",
    "away_avg_corners",
    "match_xg_home",
    "match_xg_away",
    "minute",
    "home_possession",
    "away_possession",
    "home_shots_on_target",
    "away_shots_on_target",
]


def generate_synthetic_dataset(n_samples: int = 5000, random_state: int = 42) -> pd.DataFrame:
    """Gera um dataset sintético estatisticamente plausível para demonstração.

    As relações entre features e alvo são construídas com algum sinal real
    (ex.: mais xG combinado -> maior probabilidade de mais golos) mais
    ruído aleatório, para que o modelo tenha algo genuíno para aprender
    sem depender de dados reais.
    """
    rng = np.random.default_rng(random_state)

    home_avg_goals_scored = rng.normal(1.4, 0.4, n_samples).clip(0.2, 3.5)
    away_avg_goals_scored = rng.normal(1.1, 0.4, n_samples).clip(0.2, 3.5)
    home_avg_goals_conceded = rng.normal(1.2, 0.4, n_samples).clip(0.2, 3.5)
    away_avg_goals_conceded = rng.normal(1.4, 0.4, n_samples).clip(0.2, 3.5)
    home_avg_corners = rng.normal(5.5, 1.5, n_samples).clip(1, 12)
    away_avg_corners = rng.normal(4.5, 1.5, n_samples).clip(1, 12)
    match_xg_home = rng.gamma(2.0, 0.7, n_samples)
    match_xg_away = rng.gamma(1.7, 0.7, n_samples)
    minute = rng.integers(1, 90, n_samples)
    home_possession = rng.normal(50, 10, n_samples).clip(20, 80)
    away_possession = 100 - home_possession
    home_shots_on_target = rng.poisson(4, n_samples)
    away_shots_on_target = rng.poisson(3, n_samples)

    df = pd.DataFrame(
        {
            "home_avg_goals_scored": home_avg_goals_scored,
            "away_avg_goals_scored": away_avg_goals_scored,
            "home_avg_goals_conceded": home_avg_goals_conceded,
            "away_avg_goals_conceded": away_avg_goals_conceded,
            "home_avg_corners": home_avg_corners,
            "away_avg_corners": away_avg_corners,
            "match_xg_home": match_xg_home,
            "match_xg_away": match_xg_away,
            "minute": minute,
            "home_possession": home_possession,
            "away_possession": away_possession,
            "home_shots_on_target": home_shots_on_target,
            "away_shots_on_target": away_shots_on_target,
        }
    )

    # --- Alvo 1: mais de 0.5 golos na 2ª parte ---
    combined_xg = match_xg_home + match_xg_away
    second_half_signal = combined_xg * (1 - minute / 100) + rng.normal(0, 0.5, n_samples)
    df["target_over_05_2nd_half"] = (second_half_signal > np.median(second_half_signal)).astype(int)

    # --- Alvo 2: próximo golo (0=nenhum, 1=casa, 2=fora) ---
    home_strength = home_avg_goals_scored - away_avg_goals_conceded + match_xg_home
    away_strength = away_avg_goals_scored - home_avg_goals_conceded + match_xg_away
    noise = rng.normal(0, 1.0, n_samples)
    next_goal = np.where(
        home_strength + noise > away_strength + rng.normal(0, 1.0, n_samples) + 0.3,
        1,
        np.where(away_strength > home_strength, 2, 0),
    )
    df["target_next_goal"] = next_goal

    # --- Alvo 3: mais de 9.5 cantos ---
    total_corners_signal = home_avg_corners + away_avg_corners + rng.normal(0, 2, n_samples)
    df["target_over_95_corners"] = (total_corners_signal > 9.5).astype(int)

    return df


def _train_binary_classifier(df: pd.DataFrame, target_col: str, model_name: str) -> dict:
    X = df[FEATURE_COLUMNS]
    y = df[target_col]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=20,
        random_state=42,
        n_jobs=-1,
    )

    # Validação cruzada (5-fold) para estimar generalização e evitar overfitting
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_proba = cross_val_predict(model, X_train, y_train, cv=cv, method="predict_proba")[:, 1]
    cv_auc = roc_auc_score(y_train, cv_proba)
    cv_brier = brier_score_loss(y_train, cv_proba)

    model.fit(X_train, y_train)
    test_proba = model.predict_proba(X_test)[:, 1]
    test_auc = roc_auc_score(y_test, test_proba)
    test_report = classification_report(y_test, model.predict(X_test), zero_division=0)

    logger.info("[%s] CV AUC=%.3f | CV Brier=%.3f | Test AUC=%.3f", model_name, cv_auc, cv_brier, test_auc)
    logger.info("[%s] Relatório no conjunto de teste:\n%s", model_name, test_report)

    Path(settings.MODEL_DIR).mkdir(parents=True, exist_ok=True)
    model_path = Path(settings.MODEL_DIR) / f"{model_name}.joblib"
    joblib.dump(model, model_path)

    return {
        "model_name": model_name,
        "cv_auc": cv_auc,
        "cv_brier": cv_brier,
        "test_auc": test_auc,
        "model_path": str(model_path),
    }


def train_all_models(df: pd.DataFrame | None = None) -> list[dict]:
    """Treina os três modelos-alvo e devolve um resumo de métricas."""
    if df is None:
        logger.warning(
            "A treinar com DADOS SINTÉTICOS. Substitui por dados reais antes de usar em produção."
        )
        df = generate_synthetic_dataset()

    results = [
        _train_binary_classifier(df, "target_over_05_2nd_half", "over_05_2nd_half"),
        _train_binary_classifier(df, "target_over_95_corners", "over_95_corners"),
    ]

    # Próximo golo é multiclasse (0/1/2) — treinado à parte com predict_proba de 3 colunas
    X = df[FEATURE_COLUMNS]
    y = df["target_next_goal"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    model = RandomForestClassifier(n_estimators=300, max_depth=8, min_samples_leaf=20, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    test_acc = model.score(X_test, y_test)
    Path(settings.MODEL_DIR).mkdir(parents=True, exist_ok=True)
    model_path = Path(settings.MODEL_DIR) / "next_goal.joblib"
    joblib.dump(model, model_path)
    logger.info("[next_goal] Accuracy no teste=%.3f", test_acc)
    results.append({"model_name": "next_goal", "test_accuracy": test_acc, "model_path": str(model_path)})

    return results


def load_model(model_name: str):
    model_path = Path(settings.MODEL_DIR) / f"{model_name}.joblib"
    if not model_path.exists():
        raise FileNotFoundError(
            f"Modelo '{model_name}' não encontrado em {model_path}. Corre `python model_trainer.py` primeiro."
        )
    return joblib.load(model_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    summary = train_all_models()
    print("\nResumo do treino:")
    for r in summary:
        print(f"  - {r}")
