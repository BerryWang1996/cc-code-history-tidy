from cc_history_tidy.account_config import (
    AccountDisplay,
    AccountLabelConfig,
    load_account_label_config,
    save_account_label_config,
)


def test_missing_account_config_uses_safe_default_label(tmp_path):
    config = load_account_label_config(tmp_path / "missing.json")

    display = config.display_for("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

    assert display.label.startswith("Account ")
    assert "aaaaaaaa" not in display.label


def test_account_config_round_trips_labels(tmp_path):
    path = tmp_path / "account-groups.json"
    config = AccountLabelConfig(
        accounts={
            "source-account": AccountDisplay(label="Old Work"),
        }
    )

    save_account_label_config(config, path)
    loaded = load_account_label_config(path)

    assert loaded.display_for("source-account") == AccountDisplay(
        label="Old Work",
    )
