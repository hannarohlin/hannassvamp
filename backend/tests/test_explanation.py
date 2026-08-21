from app.services.explanation import build_explanation

WEIGHTS = {"weather": 0.1, "forest": 2.0, "history": 7.0, "bias": -3.5}
IN_SEASON = 0.9
OUT_OF_SEASON = 0.1


def test_explanation_highlights_history_when_it_dominates():
    text = build_explanation(
        "gulkantarell",
        WEIGHTS,
        weather_score=0.5,
        forest_score=0.5,
        history_score=0.9,
        land_cover_label="112 Granskog på fastmark",
        soil_label=None,
        moisture_mm=2.0,
        avg_temp_c=14.0,
        nearby_observation_count=5,
        season_score=IN_SEASON,
    )

    assert "5 kända fynd" in text


def test_explanation_mentions_forest_type_in_readable_form():
    text = build_explanation(
        "trumpetsvamp_svart",
        WEIGHTS,
        weather_score=0.5,
        forest_score=0.95,
        history_score=0.3,
        land_cover_label="116 Ädellövskog på fastmark",
        soil_label=None,
        moisture_mm=2.0,
        avg_temp_c=14.0,
        nearby_observation_count=0,
        season_score=IN_SEASON,
    )

    assert "ädellövskog" in text.lower()
    assert "116" not in text
    assert "på fastmark" not in text


def test_explanation_falls_back_when_no_concrete_details_available():
    text = build_explanation(
        "trattkantarell",
        WEIGHTS,
        weather_score=0.5,
        forest_score=0.1,
        history_score=0.3,
        land_cover_label=None,
        soil_label=None,
        moisture_mm=None,
        avg_temp_c=None,
        nearby_observation_count=0,
        season_score=IN_SEASON,
    )

    assert text
    assert isinstance(text, str)


def test_explanation_mentions_weather_when_it_is_the_only_available_detail():
    text = build_explanation(
        "gulkantarell",
        {"weather": 5.0, "forest": 0.0, "history": 0.0, "bias": -3.5},
        weather_score=0.9,
        forest_score=0.1,
        history_score=0.3,
        land_cover_label=None,
        soil_label=None,
        moisture_mm=20.0,
        avg_temp_c=15.0,
        nearby_observation_count=0,
        season_score=IN_SEASON,
    )

    assert "fuktig mark" in text.lower() or "temperatur" in text.lower()


def test_explanation_mentions_low_season_when_score_is_low():
    text = build_explanation(
        "trattkantarell",
        WEIGHTS,
        weather_score=0.5,
        forest_score=0.5,
        history_score=0.9,
        land_cover_label="112 Granskog på fastmark",
        soil_label=None,
        moisture_mm=2.0,
        avg_temp_c=14.0,
        nearby_observation_count=5,
        season_score=OUT_OF_SEASON,
    )

    assert "utanför högsäsong" in text.lower()


def test_explanation_includes_soil_type_alongside_forest_type():
    text = build_explanation(
        "trumpetsvamp_rod",
        WEIGHTS,
        weather_score=0.5,
        forest_score=0.95,
        history_score=0.3,
        land_cover_label="112 Granskog på fastmark",
        soil_label="Sandig morän",
        moisture_mm=2.0,
        avg_temp_c=14.0,
        nearby_observation_count=0,
        season_score=IN_SEASON,
    )

    assert "granskog" in text.lower()
    assert "sandig morän" in text.lower()


def test_explanation_never_mentions_water_as_soil_type():
    # Jordarts-hinken (~5km) kan råka träffa en sjö/kust nära en
    # skogscell (verifierat i praktiken) — "vatten" ska aldrig visas
    # som jordart för en cell som NMD redan klassat som skog.
    text = build_explanation(
        "gulkantarell",
        WEIGHTS,
        weather_score=0.5,
        forest_score=0.95,
        history_score=0.3,
        land_cover_label="114 Lövblandad barrskog på fastmark",
        soil_label="Vatten",
        moisture_mm=2.0,
        avg_temp_c=14.0,
        nearby_observation_count=0,
        season_score=IN_SEASON,
    )

    assert "vatten" not in text.lower()
    assert "lövblandad barrskog" in text.lower()


def test_explanation_omits_season_phrase_when_in_season():
    text = build_explanation(
        "trattkantarell",
        WEIGHTS,
        weather_score=0.5,
        forest_score=0.5,
        history_score=0.9,
        land_cover_label="112 Granskog på fastmark",
        soil_label=None,
        moisture_mm=2.0,
        avg_temp_c=14.0,
        nearby_observation_count=5,
        season_score=IN_SEASON,
    )

    assert "högsäsong" not in text.lower()
