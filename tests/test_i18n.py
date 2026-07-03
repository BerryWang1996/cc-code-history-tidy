import json

from cc_history_tidy import i18n


def test_tr_formats_and_switches_language():
    i18n.set_language("zh")
    zh = i18n.tr("status.copied_n", n=2)
    i18n.set_language("en")
    en = i18n.tr("status.copied_n", n=2)
    assert "2" in zh and "2" in en
    assert zh != en


def test_missing_key_falls_back_to_zh():
    i18n.set_language("en")
    removed = i18n.LANGS["en"].pop("badge.move")
    try:
        assert i18n.tr("badge.move") == i18n.LANGS["zh"]["badge.move"]
    finally:
        i18n.LANGS["en"]["badge.move"] = removed


def test_all_keys_exist_in_both_languages():
    assert set(i18n.LANGS["zh"]) == set(i18n.LANGS["en"])


def test_detect_default_language_prefers_settings(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"language": "en"}), encoding="utf-8")
    assert i18n.detect_default_language(settings) == "en"


def test_detect_default_language_survives_corrupt_settings(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{broken", encoding="utf-8")
    assert i18n.detect_default_language(settings) in {"zh", "en"}


def test_save_language_persists(tmp_path):
    settings = tmp_path / "settings.json"
    i18n.save_language("en", settings)
    assert i18n.detect_default_language(settings) == "en"
