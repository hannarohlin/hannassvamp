from app.data_sources import sgu


def test_soil_factor_is_bounded_for_all_species():
    labels = [None, "Sandig morän", "Postglacial lera", "Isälvssediment", "Urberg", "Kärrtorv", "Fyllning", "Okänd jordart"]
    for species_key in sgu.SPECIES_SOIL_PREFERENCES:
        for label in labels:
            factor = sgu.soil_factor(label, species_key)
            assert sgu.SOIL_FACTOR_MIN <= factor <= sgu.SOIL_FACTOR_MAX


def test_soil_factor_returns_neutral_for_missing_label():
    for species_key in sgu.SPECIES_SOIL_PREFERENCES:
        assert sgu.soil_factor(None, species_key) == sgu.NEUTRAL_SOIL_FACTOR


def test_soil_factor_favors_isalvssediment_for_gulkantarell():
    # Väldränerad rullstensås ska gynna gulkantarell mer än vattenhållande lera.
    well_drained = sgu.soil_factor("Isälvssediment", "gulkantarell")
    clay = sgu.soil_factor("Lera", "gulkantarell")

    assert well_drained > clay


def test_soil_factor_favors_clay_for_trumpetsvamp_svart_over_gulkantarell():
    # Kalkgynnad, ädellövassocierad art ska gynnas mer av lera än den
    # väldränerade sand/tallskogsarten gulkantarell.
    clay_score_black = sgu.soil_factor("Lera", "trumpetsvamp_svart")
    clay_score_yellow = sgu.soil_factor("Lera", "gulkantarell")

    assert clay_score_black > clay_score_yellow


def test_soil_factor_longest_match_wins():
    # "Sandig morän" ska inte råka matchas av den kortare, mer
    # generiska frasen "morän" om en mer specifik fras finns.
    specific = sgu.soil_factor("Sandig morän", "trattkantarell")
    generic = sgu.soil_factor("Morän", "trattkantarell")

    assert specific != generic


def test_soil_label_to_phrase_lowercases_and_strips():
    assert sgu.soil_label_to_phrase("Sandig morän") == "sandig morän"
    assert sgu.soil_label_to_phrase(None) is None
    assert sgu.soil_label_to_phrase("  ") is None
