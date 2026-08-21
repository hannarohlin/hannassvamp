from app.services.logistic_regression import fit_logistic_regression, predict_probability


def test_learns_positive_weight_on_predictive_feature():
    # x0 är starkt korrelerad med etiketten, x1 är brus.
    features = [
        [0.9, 0.5], [0.85, 0.1], [0.95, 0.8], [0.8, 0.3],
        [0.1, 0.6], [0.05, 0.9], [0.15, 0.2], [0.2, 0.4],
    ]
    labels = [1, 1, 1, 1, 0, 0, 0, 0]

    weights, bias = fit_logistic_regression(features, labels, iterations=1000)

    assert weights[0] > 0
    assert weights[0] > abs(weights[1])


def test_predict_probability_is_higher_for_positive_like_input():
    features = [[0.9, 0.9], [0.8, 0.8], [0.1, 0.1], [0.2, 0.2]]
    labels = [1, 1, 0, 0]

    weights, bias = fit_logistic_regression(features, labels, iterations=1000)

    high = predict_probability(weights, bias, [0.9, 0.9])
    low = predict_probability(weights, bias, [0.1, 0.1])

    assert 0 <= high <= 1
    assert 0 <= low <= 1
    assert high > low
