from cc_history_tidy.group_labels import _looks_like_better_label


def test_email_does_not_replace_named_group_label():
    assert not _looks_like_better_label("qq951332197@gmail.com", "Barry Wang")


def test_named_group_label_replaces_email_fallback():
    assert _looks_like_better_label("Barry Wang", "qq951332197@gmail.com")
