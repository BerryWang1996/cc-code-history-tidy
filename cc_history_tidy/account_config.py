from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


@dataclass(frozen=True)
class AccountDisplay:
    label: str


@dataclass(frozen=True)
class AccountLabelConfig:
    accounts: dict[str, AccountDisplay]

    def display_for(self, account_uuid: str) -> AccountDisplay:
        configured = self.accounts.get(account_uuid)
        if configured is not None:
            return configured
        digest = hashlib.sha256(account_uuid.encode("utf-8")).hexdigest()[:8].upper()
        return AccountDisplay(label=f"Account {digest}")


def load_account_label_config(path: Path) -> AccountLabelConfig:
    if not path.exists():
        return AccountLabelConfig(accounts={})
    data = json.loads(path.read_text(encoding="utf-8"))
    accounts = {
        account_uuid: AccountDisplay(
            label=str(display.get("label") or account_uuid),
        )
        for account_uuid, display in data.get("accounts", {}).items()
        if isinstance(display, dict)
    }
    return AccountLabelConfig(accounts=accounts)


def save_account_label_config(config: AccountLabelConfig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "accounts": {
                    account_uuid: {
                        "label": display.label,
                    }
                    for account_uuid, display in sorted(config.accounts.items())
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )


# Backward-compatible aliases for early internal builds.
AccountGroupConfig = AccountLabelConfig
load_account_group_config = load_account_label_config
save_account_group_config = save_account_label_config
