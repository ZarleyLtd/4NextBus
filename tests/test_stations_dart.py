from src.modes.dart.stations import (
    build_station, find_station, match_platforms, parse_direction,
    bad_direction_speech, matching_headsigns, normalize_name, options_speech,
    split_raw_platforms, split_station_and_direction, spoken_name,
)

PEARSE_ID = "8220IR0134"


def pease():
    return build_station("Dublin Pearse", split_raw_platforms(
        PEARSE_ID, "1", "Dublin Pearse",
        ["Howth", "Malahide", "Dublin Connolly", "Bray (Daly)", "Greystones", "Grand Canal Dock"],
    ))


def howth_junction():
    return build_station("Howth Junction and Donaghmede", split_raw_platforms(
        "8240IR0025", "2", "Howth Junction and Donaghmede",
        ["Howth", "Malahide", "Bray (Daly)", "Greystones", "Grand Canal Dock"],
    ))


def blackrock():
    return build_station("Blackrock", split_raw_platforms(
        "8250IR0030", "3", "Blackrock",
        ["Howth", "Malahide", "Dublin Connolly", "Bray (Daly)", "Greystones"],
    ))


def howth():
    return build_station("Howth", split_raw_platforms(
        "8240IR0017", "4", "Howth",
        ["Bray (Daly)", "Greystones", "Grand Canal Dock", "Dublin Connolly"],
    ))


def greystones():
    return build_station("Greystones", split_raw_platforms(
        "8350IR0122", "5", "Greystones",
        ["Howth", "Malahide", "Bray (Daly)", "Dublin Connolly"],
    ))


def test_pearse_splits_north_and_south():
    st = pease()
    assert st.spoken == "Pearse"
    assert st.city_centre is True
    north = next(p for p in st.platforms if "northbound" in p.cardinals)
    south = next(p for p in st.platforms if "southbound" in p.cardinals)
    assert north.stop_id == south.stop_id == PEARSE_ID
    assert "Howth" in north.headsigns and "Malahide" in north.headsigns
    assert "Bray (Daly)" in south.headsigns and "Greystones" in south.headsigns


def test_match_direction_phrases():
    st = pease()
    north = match_platforms(st, "northbound")[0]
    south = match_platforms(st, parse_direction("south"))[0]
    assert "Howth" in north.headsigns
    assert "Bray (Daly)" in south.headsigns
    assert match_platforms(st, parse_direction("towards Bray"))[0].stop_id == PEARSE_ID
    assert "Bray (Daly)" in matching_headsigns(
        match_platforms(st, parse_direction("towards Bray"))[0], parse_direction("towards Bray"))
    assert match_platforms(st, "eastbound") == []


def test_city_centre_towards_the_city_is_empty():
    st = pease()
    assert match_platforms(st, "city") == []
    assert "ambiguous" in bad_direction_speech(st, "city").lower()


def test_blackrock_towards_city_is_northbound():
    st = blackrock()
    assert st.city_centre is False
    city = match_platforms(st, parse_direction("towards the city"))
    assert len(city) == 1 and "northbound" in city[0].cardinals
    assert match_platforms(st, "southbound")[0] is not city[0]


def test_howth_junction_northbound_covers_both_branches():
    st = howth_junction()
    north = match_platforms(st, "northbound")
    assert len(north) == 1
    assert "Howth" in north[0].headsigns and "Malahide" in north[0].headsigns
    howth_only = matching_headsigns(north[0], parse_direction("towards Howth"))
    assert howth_only == ["Howth"]
    malahide_only = matching_headsigns(north[0], parse_direction("towards Malahide"))
    assert malahide_only == ["Malahide"]


def test_termini_have_one_usable_direction():
    assert [p.cardinals[0] for p in howth().usable_platforms()] == ["southbound"]
    assert [p.cardinals[0] for p in greystones().usable_platforms()] == ["northbound"]
    greystones_north = match_platforms(greystones(), "northbound")[0]
    assert "Bray (Daly)" in greystones_north.headsigns


def test_find_station_aliases():
    catalog = [pease(), howth_junction(), blackrock()]
    assert find_station(catalog, "Pearse").name == "Dublin Pearse"
    assert find_station(catalog, "dublin pearse").name == "Dublin Pearse"
    assert find_station(catalog, "howth junction").name == "Howth Junction and Donaghmede"
    assert find_station(catalog, "donaghmede").name == "Howth Junction and Donaghmede"
    assert find_station(catalog, "nowhere") is None


def test_parse_direction():
    assert parse_direction("northbound") == "northbound"
    assert parse_direction("south bound") == "southbound"
    assert parse_direction("going south") == "southbound"
    assert parse_direction("towards Bray") == "bray"
    assert parse_direction("to Greystones") == "greystones"
    assert parse_direction("the city") == "city"
    assert parse_direction("nortbound") == "northbound"
    assert parse_direction("") is None


def test_split_station_glued_direction():
    assert split_station_and_direction("Pearse southbound", None) == ("Pearse", "southbound")
    assert split_station_and_direction("Pearse going north", None) == ("Pearse", "northbound")
    assert split_station_and_direction("Pearse towards Bray", None) == ("Pearse", "bray")
    assert split_station_and_direction("Pearse southbound", "northbound") == ("Pearse", "northbound")
    assert split_station_and_direction("Pearse", None) == ("Pearse", None)
    assert split_station_and_direction("clontarf road nortbound", None) == ("clontarf road", "northbound")


def test_options_speech_lists_both():
    text = options_speech(pease())
    assert "northbound" in text and "southbound" in text


def test_normalize_strips_dart_words():
    assert normalize_name("Pearse DART") == "pearse"
    assert normalize_name("Pearse station") == "pearse"
    assert spoken_name("Bray (Daly)") == "Bray"
    assert spoken_name("Dun Laoghaire (Mallin)") == "Dun Laoghaire"
