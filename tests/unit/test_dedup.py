from copilot.ingest.dedup import NearDuplicateIndex, shingles

BASE = (
    "Thermite is an attacking operator from the FBI SWAT unit. His exothermic charge can breach "
    "reinforced walls and hatches. Defenders counter him with Bandit, Kaid and Mute, so his team "
    "must clear electronic gadgets before placing the charge. He carries the 556xi assault rifle "
    "or the M1014 shotgun and is one of the most picked attackers in competitive play. "
    "Before the round starts he scouts with his drone, looking for reinforced walls near the "
    "objective, and calls out which ones the hard breach should target. When the defenders run "
    "an electronic denial setup, Thermite waits for Thatcher's EMP grenades or Twitch's shock "
    "drone, then places the charge and detonates it from a safe distance to open the site."
)
NEAR = BASE.replace("most picked", "most often picked")
OTHER = (
    "Clubhouse is a map set in a biker gang hideout in the countryside. The bomb sites are the "
    "bar and stock room, the church and arsenal, the gym and bedroom, and the cash room and CCTV "
    "room. Defenders often roam through the garage and the construction area to delay attackers."
)


def make_index() -> NearDuplicateIndex:
    return NearDuplicateIndex(threshold=0.8, num_perm=128, shingle_words=5)


def test_shingles() -> None:
    assert shingles("a b c", 5) == {"a b c"}
    assert shingles("", 5) == set()
    assert shingles("a b c d", 2) == {"a b", "b c", "c d"}


def test_detects_near_duplicate() -> None:
    idx = make_index()
    idx.add("1", BASE)
    assert idx.find_duplicate(NEAR) == "1"


def test_distinct_documents_are_not_duplicates() -> None:
    idx = make_index()
    idx.add("1", BASE)
    assert idx.find_duplicate(OTHER) is None


def test_exclude_self_and_readd() -> None:
    idx = make_index()
    idx.add("1", BASE)
    assert idx.find_duplicate(NEAR, exclude="1") is None
    idx.add("1", OTHER)  # re-adding replaces the old signature
    assert len(idx) == 1 and "1" in idx
    assert idx.find_duplicate(BASE) is None
