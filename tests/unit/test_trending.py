from cti_api.services.trending import rank_trends


def test_change_pct_only_with_enough_baseline():
    items = rank_trends({("actor", "Qilin", None): [5, 6, 12]}, {("actor", "Qilin", None): 5})
    assert items[0].count == 23 and items[0].prev_count == 5 and items[0].change_pct == 360
    items = rank_trends({("actor", "X", None): [2, 2]}, {("actor", "X", None): 2})
    assert items[0].change_pct is None and items[0].is_new is False


def test_new_entity_flagged():
    items = rank_trends({("ttp", "Spearphishing Link", "T1566.002"): [1, 1, 3]}, {})
    assert items[0].is_new is True and items[0].change_pct is None
    assert items[0].ttp_id == "T1566.002"


def test_below_min_count_dropped_and_ranked_by_absolute_rise():
    items = rank_trends(
        {("actor", "A", None): [1, 1], ("actor", "B", None): [10], ("actor", "C", None): [6]},
        {("actor", "B", None): 9, ("actor", "C", None): 0},
    )
    assert [i.name for i in items] == ["C", "B"]  # C rose 6, B rose 1, A (2) under min_count


def test_falling_entities_excluded():
    assert rank_trends({("actor", "D", None): [4]}, {("actor", "D", None): 9}) == []
