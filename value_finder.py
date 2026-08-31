"""
value_finder.py
----------------
Lógica central de "value betting":

1. Converte odds em probabilidades implícitas (prob_impl = 1 / odd)
2. Remove o overround (margem da casa) normalizando as probabilidades
   de todas as seleções de um mercado para somarem 100%
3. Compara com a probabilidade prevista pelo modelo preditivo
4. Calcula o Valor Esperado: EV = (prob_modelo * odd) - 1
5. Gera um "sinal" quando EV > EV_THRESHOLD

Aviso: o EV só é tão bom quanto o modelo que estima prob_modelo. Um EV
positivo com um modelo mal calibrado é apenas ruído com aparência de sinal.
"""

import logging
from dataclasses import dataclass

from config import settings

logger = logging.getLogger("opusports.value_finder")


@dataclass
class ValueSignal:
    fixture_id: int
    market: str
    selection: str
    model_probability: float
    implied_probability: float
    odd: float
    expected_value: float

    @property
    def is_valuable(self) -> bool:
        return self.expected_value > settings.EV_THRESHOLD


def implied_probability(odd: float) -> float:
    """prob_impl = 1 / odd"""
    if odd <= 1.0:
        raise ValueError(f"Odd inválida: {odd} (tem de ser > 1.0)")
    return 1.0 / odd


def remove_overround(odds: list[float]) -> list[float]:
    """Normaliza probabilidades implícitas de um mercado completo para
    somarem 1.0, removendo a margem da casa de apostas (overround).

    Exemplo: odds [1.90, 2.10, 4.00] para um mercado 1X2 somam mais de
    100% de probabilidade implícita bruta — a diferença é a margem.
    """
    raw_probs = [implied_probability(o) for o in odds]
    total = sum(raw_probs)
    if total <= 0:
        return raw_probs
    return [p / total for p in raw_probs]


def expected_value(model_probability: float, odd: float) -> float:
    """EV = (prob_modelo * odd) - 1

    EV > 0 significa que, em média e a longo prazo, a aposta é lucrativa
    SE a probabilidade do modelo estiver bem calibrada.
    """
    return (model_probability * odd) - 1.0


def evaluate_market(
    fixture_id: int,
    market: str,
    selections_odds: dict[str, float],
    model_probabilities: dict[str, float],
) -> list[ValueSignal]:
    """Avalia um mercado completo (todas as seleções) e devolve sinais de valor.

    Args:
        fixture_id: id do jogo
        market: nome do mercado (ex.: "Próximo Golo", "Mais de 9.5 Cantos")
        selections_odds: {"Casa": 2.10, "Fora": 3.40, "Nenhum": 3.10}
        model_probabilities: {"Casa": 0.42, "Fora": 0.25, "Nenhum": 0.33}
    """
    selections = list(selections_odds.keys())
    odds_list = [selections_odds[s] for s in selections]
    normalized_probs = remove_overround(odds_list)
    implied = dict(zip(selections, normalized_probs))

    signals = []
    for selection in selections:
        odd = selections_odds[selection]
        model_prob = model_probabilities.get(selection)
        if model_prob is None:
            logger.debug("Sem probabilidade do modelo para '%s' — a ignorar", selection)
            continue

        ev = expected_value(model_prob, odd)
        signal = ValueSignal(
            fixture_id=fixture_id,
            market=market,
            selection=selection,
            model_probability=model_prob,
            implied_probability=implied[selection],
            odd=odd,
            expected_value=ev,
        )
        signals.append(signal)

        if signal.is_valuable:
            logger.info(
                "VALOR ENCONTRADO: fixture=%s market=%s selection=%s EV=%.1f%%",
                fixture_id, market, selection, ev * 100,
            )

    return signals


def filter_valuable_signals(signals: list[ValueSignal]) -> list[ValueSignal]:
    return [s for s in signals if s.is_valuable]


if __name__ == "__main__":
    # Exemplo standalone
    logging.basicConfig(level=logging.INFO)
    example_odds = {"Casa": 2.10, "Fora": 3.40, "Nenhum": 3.10}
    example_model_probs = {"Casa": 0.50, "Fora": 0.25, "Nenhum": 0.25}

    signals = evaluate_market(
        fixture_id=123456,
        market="Próximo Golo",
        selections_odds=example_odds,
        model_probabilities=example_model_probs,
    )
    for s in signals:
        print(f"{s.selection}: EV={s.expected_value:.3f} ({'VALOR' if s.is_valuable else 'sem valor'})")
