import pytest

from app.data_sources import smhi


def test_temperature_to_score_is_bounded():
    for temp_c in [-10, 0, 10, 15, 20, 30, 45]:
        score = smhi.temperature_to_score(temp_c)
        assert 0 <= score <= 1


def test_temperature_to_score_favors_ideal_range():
    ideal = smhi.temperature_to_score(15)
    cold = smhi.temperature_to_score(-5)
    hot = smhi.temperature_to_score(35)

    assert ideal > cold
    assert ideal > hot


def test_rolling_moisture_mm_accumulates_recent_rain():
    # 21 torra dagar följt av ett rejält regn ska ge en tydligt högre
    # ackumulerad fukt än 21 helt torra dagar.
    dry_days = [0.0] * 21
    temps = [15.0] * 21
    rained_recently = dry_days[:-1] + [20.0]

    dry_moisture = smhi.rolling_moisture_mm(dry_days, temps)
    wet_moisture = smhi.rolling_moisture_mm(rained_recently, temps)

    assert wet_moisture > dry_moisture
    assert dry_moisture == pytest.approx(0.0)


def test_rolling_moisture_mm_decays_over_time():
    # Regn för 20 dagar sedan ska bidra MINDRE än samma regn igår,
    # eftersom fukten avklingar dag för dag.
    temps = [15.0] * 21
    rained_long_ago = [20.0] + [0.0] * 20
    rained_yesterday = [0.0] * 20 + [20.0]

    old_rain_moisture = smhi.rolling_moisture_mm(rained_long_ago, temps)
    recent_rain_moisture = smhi.rolling_moisture_mm(rained_yesterday, temps)

    assert recent_rain_moisture > old_rain_moisture


def test_rolling_moisture_mm_dries_out_faster_when_warm():
    # Samma regnmängd ska klinga av snabbare (lägre kvarvarande fukt)
    # ju varmare det är, eftersom avdunstningen är högre.
    precip = [20.0] + [0.0] * 20
    cool_moisture = smhi.rolling_moisture_mm(precip, [5.0] * 21)
    warm_moisture = smhi.rolling_moisture_mm(precip, [25.0] * 21)

    assert cool_moisture > warm_moisture


def test_rolling_moisture_to_score_is_bounded():
    for mm in [-5, 0, 10, 25, 50, 200]:
        score = smhi.rolling_moisture_to_score(mm)
        assert 0 <= score <= 1


def test_rolling_moisture_to_score_favors_moderate_accumulation():
    dry = smhi.rolling_moisture_to_score(0)
    moderate = smhi.rolling_moisture_to_score(25)
    flooded = smhi.rolling_moisture_to_score(200)

    assert moderate > dry
    assert moderate > flooded


def test_rolling_weather_score_reflects_dry_spell():
    dry_spell = smhi.rolling_weather_score([0.0] * 21, [18.0] * 21)
    wet_spell = smhi.rolling_weather_score([0.0] * 20 + [25.0], [15.0] * 21)

    assert wet_spell["score"] > dry_spell["score"]
    assert dry_spell["moisture_mm"] == pytest.approx(0.0)


def test_extract_month_finds_matching_year_month():
    data = {
        "dates": ["2024-06", "2024-07", "2024-08"],
        "point_values": [{"p": [40.0, 80.0, 90.0], "t": [14.0, 16.0, 17.0]}],
    }
    assert smhi.extract_month(data, 2024, 7) == pytest.approx((80.0, 16.0))


def test_extract_month_returns_none_when_missing():
    data = {"dates": ["2024-06"], "point_values": [{"p": [40.0], "t": [14.0]}]}
    assert smhi.extract_month(data, 2024, 12) is None


def test_extract_month_returns_none_when_value_is_null():
    # PTHBV kan sakna enskilda värden (t.ex. kust/skärgård, en
    # preliminär månad) utan att hela månaden saknas i `dates`.
    data = {"dates": ["2024-06"], "point_values": [{"p": [None], "t": [14.0]}]}
    assert smhi.extract_month(data, 2024, 6) is None


def test_monthly_precipitation_to_score_is_bounded():
    for mm in [-5, 0, 25, 75, 120, 300]:
        score = smhi.monthly_precipitation_to_score(mm)
        assert 0 <= score <= 1


def test_monthly_precipitation_to_score_favors_moderate_range():
    dry = smhi.monthly_precipitation_to_score(5)
    moderate = smhi.monthly_precipitation_to_score(75)
    flood = smhi.monthly_precipitation_to_score(400)

    assert moderate > dry
    assert moderate > flood


def test_historical_weather_score_combines_precipitation_and_temperature():
    favorable = smhi.historical_weather_score(75, 15)
    unfavorable = smhi.historical_weather_score(0, -5)

    assert favorable > unfavorable
