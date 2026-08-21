"""Minimal logistisk regression (batch gradient descent), utan externa beroenden.

Används av `scripts/calibrate_weights.py` för att skatta hur mycket
väder-, skogs- och historik-scoren egentligen bidrar till att förklara
var kantarellfynd sker, istället för de gissade vikterna i
`app/services/prediction.py`. Med bara 3 features och några hundra
träningspunkter är ren Python fullt tillräckligt snabbt — ingen
anledning att dra in numpy/scikit-learn för det här.
"""

from __future__ import annotations

import math


def sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def fit_logistic_regression(
    features: list[list[float]],
    labels: list[int],
    learning_rate: float = 0.5,
    iterations: int = 3000,
    l2: float = 0.001,
) -> tuple[list[float], float]:
    """Skattar (vikter, intercept) via batch gradient descent.

    `features` är redan 0–1-normaliserade scores, så ingen standardisering
    behövs. `l2` är en lätt regularisering för att undvika att en enskild
    feature får en orimligt extrem vikt på ett litet dataset.
    """
    n_samples = len(features)
    n_features = len(features[0])
    weights = [0.0] * n_features
    bias = 0.0

    for _ in range(iterations):
        grad_w = [0.0] * n_features
        grad_b = 0.0

        for x, y in zip(features, labels):
            z = bias + sum(w * xi for w, xi in zip(weights, x))
            error = sigmoid(z) - y
            for j in range(n_features):
                grad_w[j] += error * x[j]
            grad_b += error

        for j in range(n_features):
            grad_w[j] = grad_w[j] / n_samples + l2 * weights[j]
            weights[j] -= learning_rate * grad_w[j]
        bias -= learning_rate * (grad_b / n_samples)

    return weights, bias


def predict_probability(weights: list[float], bias: float, x: list[float]) -> float:
    z = bias + sum(w * xi for w, xi in zip(weights, x))
    return sigmoid(z)
