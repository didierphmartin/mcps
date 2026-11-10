from parsing.types import suffixes_for, ALL_SUFFIXES


def test_empty_means_all():
    assert sorted(suffixes_for(None)) == sorted(ALL_SUFFIXES)
    assert sorted(suffixes_for([])) == sorted(ALL_SUFFIXES)


def test_filter_maps_doctypes_to_suffixes():
    assert sorted(suffixes_for(["pdf", "word"])) == [".doc", ".docx", ".pdf"]


def test_unknown_type_ignored():
    assert suffixes_for(["nope"]) == []
    assert sorted(suffixes_for(["pdf", "nope"])) == [".pdf"]
