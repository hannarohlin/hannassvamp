from app.data_sources import nmd

SPECIES_KEYS = ["gulkantarell", "trattkantarell", "trumpetsvamp_svart", "trumpetsvamp_rod"]


def test_land_cover_label_to_forest_score_is_bounded():
    labels = [
        None,
        "111 Tallskog på fastmark",
        "112 Granskog på fastmark",
        "113 Barrblandskog på fastmark",
        "114 Lövblandad barrskog på fastmark",
        "115 Triviallövskog på fastmark",
        "116 Ädellövskog på fastmark",
        "117 Triviallövskog med ädellövinslag på fastmark",
        "118 Temporärt ej skog på fastmark",
        "125 Triviallövskog på våtmark",
        "3 Åkermark",
        "61 Inlandsvatten",
    ]
    for species_key in SPECIES_KEYS:
        for label in labels:
            score = nmd.land_cover_label_to_forest_score(label, species_key)
            assert 0 <= score <= 1


def test_gulkantarell_favors_mixed_conifer_forest():
    mixed = nmd.land_cover_label_to_forest_score("113 Barrblandskog på fastmark", "gulkantarell")
    pure_conifer = nmd.land_cover_label_to_forest_score("112 Granskog på fastmark", "gulkantarell")
    broadleaf = nmd.land_cover_label_to_forest_score("115 Triviallövskog på fastmark", "gulkantarell")
    non_forest = nmd.land_cover_label_to_forest_score("3 Åkermark", "gulkantarell")

    assert mixed > pure_conifer > broadleaf > non_forest


def test_trumpetsvamp_favors_broadleaf_over_conifer():
    broadleaf = nmd.land_cover_label_to_forest_score("116 Ädellövskog på fastmark", "trumpetsvamp_svart")
    conifer = nmd.land_cover_label_to_forest_score("112 Granskog på fastmark", "trumpetsvamp_svart")

    assert broadleaf > conifer

    # Motsatt ordning för gulkantarell och trattkantarell.
    assert nmd.land_cover_label_to_forest_score("112 Granskog på fastmark", "gulkantarell") > \
        nmd.land_cover_label_to_forest_score("116 Ädellövskog på fastmark", "gulkantarell")
    assert nmd.land_cover_label_to_forest_score("112 Granskog på fastmark", "trattkantarell") > \
        nmd.land_cover_label_to_forest_score("116 Ädellövskog på fastmark", "trattkantarell")


def test_trumpetsvamp_rod_favors_conifer_over_broadleaf():
    # Motsatt preferens jämfört med svart trumpetsvamp — skiljer på de
    # två arterna, inte bara en färgvariant av samma habitat-profil.
    conifer = nmd.land_cover_label_to_forest_score("112 Granskog på fastmark", "trumpetsvamp_rod")
    broadleaf = nmd.land_cover_label_to_forest_score("116 Ädellövskog på fastmark", "trumpetsvamp_rod")

    assert conifer > broadleaf


def test_trattkantarell_tolerates_wetland_better_than_gulkantarell():
    dry = "112 Granskog på fastmark"
    wet = "122 Granskog på våtmark"

    gulkantarell_ratio = nmd.land_cover_label_to_forest_score(wet, "gulkantarell") / nmd.land_cover_label_to_forest_score(dry, "gulkantarell")
    trattkantarell_ratio = nmd.land_cover_label_to_forest_score(wet, "trattkantarell") / nmd.land_cover_label_to_forest_score(dry, "trattkantarell")

    assert trattkantarell_ratio > gulkantarell_ratio


def test_missing_label_returns_neutral_score_for_all_species():
    for species_key in SPECIES_KEYS:
        assert nmd.land_cover_label_to_forest_score(None, species_key) == 0.4


def test_is_forest_label_true_for_forest_classes():
    forest_labels = [
        "111 Tallskog på fastmark",
        "112 Granskog på fastmark",
        "113 Barrblandskog på fastmark",
        "114 Lövblandad barrskog på fastmark",
        "115 Triviallövskog på fastmark",
        "116 Ädellövskog på fastmark",
        "117 Triviallövskog med ädellövinslag på fastmark",
        "118 Temporärt ej skog på fastmark",
        "125 Triviallövskog på våtmark",
    ]
    for label in forest_labels:
        assert nmd.is_forest_label(label) is True


def test_is_forest_label_false_for_non_forest_and_missing():
    non_forest_labels = [
        "3 Åkermark",
        "51 Byggnad",
        "53 Väg/järnväg",
        "61 Inlandsvatten",
        "62 Hav",
        "4 231 Gräsdominerad mark, torr",
    ]
    for label in non_forest_labels:
        assert nmd.is_forest_label(label) is False

    assert nmd.is_forest_label(None) is False
