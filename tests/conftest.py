import pytest

from cc_history_tidy import i18n


@pytest.fixture(autouse=True)
def _force_chinese_language(request, monkeypatch):
    """Pin the UI language to zh so string assertions are deterministic
    regardless of the machine's system locale or user settings.

    test_i18n exercises the real detection logic, so it is exempt from the
    detect_default_language patch."""
    if not request.module.__name__.endswith("test_i18n"):
        monkeypatch.setattr(i18n, "detect_default_language", lambda *_: "zh")
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")
