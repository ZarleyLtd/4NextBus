from src.modes.train.stations import (
    all_corridor_stops, build_station, collect_headsigns, find_station, match_platforms,
    parse_direction, bad_direction_speech, matching_headsigns, merged_platform_label,
    normalize_name, options_speech, split_raw_platforms, split_station_and_direction,
    spoken_name,
)

PEARSE_ID = "8220IR0134"


def pease():
    return build_station("Dublin Pearse", split_raw_platforms(
        PEARSE_ID, "1", "Dublin Pearse",
        ["Dundalk (Clarke)", "Drogheda (MacBride)", "Dublin Connolly",
         "Gorey", "Greystones", "Bray (Daly)"],
    ))


def blackrock():
    return build_station("Blackrock", split_raw_platforms(
        "8250IR0030", "3", "Blackrock",
        ["Dublin Connolly", "Dublin Pearse", "Gorey", "Greystones", "Bray (Daly)"],
    ))


def maynooth():
    return build_station("Maynooth", split_raw_platforms(
        "8210IR0001", "4", "Maynooth",
        ["Dublin Connolly", "Dublin Pearse", "Longford"],
    ))


def gorey():
    return build_station("Gorey", split_raw_platforms(
        "8350IR0001", "5", "Gorey",
        ["Dublin Connolly", "Dublin Pearse", "Bray (Daly)"],
    ))


DRUM_ID = "8220IR0027"


def drumcondra():
    return build_station("Drumcondra", split_raw_platforms(
        DRUM_ID, "27", "Drumcondra",
        ["Dublin Connolly", "Dublin Pearse", "Grand Canal Dock",
         "Longford", "Maynooth", "Mullingar",
         "Hazelhatch and Celbridge", "Newbridge"],
    ))


def test_pearse_splits_north_and_south():
    st = pease()
    assert st.spoken == "Pearse"
    assert st.city_centre is True
    north = next(p for p in st.platforms if "northbound" in p.cardinals)
    south = next(p for p in st.platforms if "southbound" in p.cardinals)
    assert north.stop_id == south.stop_id == PEARSE_ID
    assert "Dundalk (Clarke)" in north.headsigns
    assert "Gorey" in south.headsigns or "Bray (Daly)" in south.headsigns


def test_match_direction_phrases():
    st = pease()
    north = match_platforms(st, "northbound")[0]
    south = match_platforms(st, parse_direction("south"))[0]
    assert "Dundalk (Clarke)" in north.headsigns
    assert "Gorey" in south.headsigns or "Bray (Daly)" in south.headsigns
    towards_gorey = match_platforms(st, parse_direction("towards Gorey"))
    assert towards_gorey
    assert "Gorey" in matching_headsigns(towards_gorey[0], parse_direction("towards Gorey"))


def test_city_centre_towards_the_city_is_empty():
    st = pease()
    assert match_platforms(st, "city") == []
    assert "ambiguous" in bad_direction_speech(st, "city").lower()


def test_blackrock_towards_city_is_northbound():
    st = blackrock()
    assert st.city_centre is False
    city = match_platforms(st, parse_direction("towards the city"))
    assert len(city) == 1 and city[0].citybound
    assert match_platforms(st, "southbound")
    assert match_platforms(st, "southbound")[0] is not city[0]


def test_maynooth_city_vs_longford():
    st = maynooth()
    city = match_platforms(st, "city")
    assert city and city[0].citybound
    out = match_platforms(st, parse_direction("towards Longford"))
    assert out and "Longford" in out[0].headsigns


def test_drumcondra_westbound_matches_maynooth_and_hazelhatch():
    st = drumcondra()
    west = match_platforms(st, "westbound")
    assert len(west) == 2
    towards = {tuple(p.towards[:1]) for p in west}
    assert ("Maynooth",) in towards or any("Maynooth" in p.towards for p in west)
    assert any("Hazelhatch" in p.towards for p in west)
    city = match_platforms(st, "city")
    assert len(city) == 1 and city[0].citybound
    maynooth_only = match_platforms(st, parse_direction("towards Maynooth"))
    assert len(maynooth_only) == 1 and "Maynooth" in maynooth_only[0].towards
    heads = collect_headsigns(west, "westbound")
    assert any("Maynooth" in h for h in heads)
    assert any("Hazelhatch" in h for h in heads)
    assert merged_platform_label(st, "westbound", west) == "Drumcondra, westbound"


def test_termini_have_one_usable_direction():
    plats = gorey().usable_platforms()
    assert plats
    assert any("northbound" in p.cardinals or p.citybound for p in plats)


def test_find_station_aliases():
    catalog = [pease(), blackrock(), maynooth()]
    assert find_station(catalog, "Pearse").name == "Dublin Pearse"
    assert find_station(catalog, "dublin pearse").name == "Dublin Pearse"
    assert find_station(catalog, "Maynooth").name == "Maynooth"
    assert find_station(catalog, "nowhere") is None


def test_parse_direction():
    assert parse_direction("northbound") == "northbound"
    assert parse_direction("south bound") == "southbound"
    assert parse_direction("going south") == "southbound"
    assert parse_direction("going east") == "eastbound"
    assert parse_direction("east") == "eastbound"
    assert parse_direction("heading west") == "westbound"
    assert parse_direction("to the east") == "eastbound"
    assert parse_direction("towards Gorey") == "gorey"
    assert parse_direction("to Dundalk") == "dundalk"
    assert parse_direction("the city") == "city"
    assert parse_direction("") is None


def test_split_station_glued_direction():
    assert split_station_and_direction("Pearse southbound", None) == ("Pearse", "southbound")
    assert split_station_and_direction("Pearse going north", None) == ("Pearse", "northbound")
    assert split_station_and_direction("Broombridge going east", None) == ("Broombridge", "eastbound")
    assert split_station_and_direction("Broombridge", "going east") == ("Broombridge", "eastbound")
    assert split_station_and_direction("Broombridge", "east") == ("Broombridge", "eastbound")
    assert split_station_and_direction("maynooth westbound", None) == ("maynooth", "westbound")
    assert split_station_and_direction("Pearse towards Gorey", None) == ("Pearse", "gorey")
    assert split_station_and_direction("Pearse southbound", "northbound") == ("Pearse", "northbound")
    assert split_station_and_direction("Pearse", None) == ("Pearse", None)


def test_options_speech_lists_both():
    text = options_speech(pease())
    assert "northbound" in text or "Dundalk" in text
    assert "southbound" in text or "Gorey" in text or "Bray" in text


def test_normalize_strips_filler_words():
    assert normalize_name("Pearse DART") == "pearse"
    assert normalize_name("Pearse station") == "pearse"
    assert normalize_name("Maynooth commuter") == "maynooth"
    assert spoken_name("Bray (Daly)") == "Bray"
    assert spoken_name("Dun Laoghaire (Mallin)") == "Dun Laoghaire"
    assert spoken_name("Dundalk (Clarke)") == "Dundalk"


def test_fallback_catalog_has_national_stops():
    names = all_corridor_stops()
    assert "Maynooth" in names
    assert "Cobh" in names
    assert "Limerick Junction" in names
    assert "Dundalk (Clarke)" in names
