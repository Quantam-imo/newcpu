from __future__ import annotations

from dataclasses import dataclass

from astroquant.core.prop_profiles import (
    profile_for,
    profile_risk_pct,
    supported_account_keys,
)


@dataclass
class ManagedAccount:
    account_key: str
    mode: str = "STANDARD"
    active: bool = False


class DynamicPropEngine:
    def __init__(self):
        keys = supported_account_keys()
        self.accounts: dict[str, ManagedAccount] = {
            key: ManagedAccount(account_key=key, mode="STANDARD", active=(key == "50K"))
            for key in keys
        }
        self.primary_account_key = "50K"

    def configure(
        self,
        active_accounts: list[str] | None = None,
        primary_account: str | None = None,
        mode_map: dict | None = None,
        default_mode: str | None = None,
    ):
        mode_map = mode_map or {}
        all_keys = set(self.accounts.keys())

        if active_accounts is not None:
            normalized = {str(value).upper().strip() for value in list(active_accounts or [])}
            normalized = {value for value in normalized if value in all_keys}
            if not normalized:
                normalized = {self.primary_account_key if self.primary_account_key in all_keys else "50K"}
            for key in self.accounts:
                self.accounts[key].active = key in normalized

        if default_mode is not None:
            for key in self.accounts:
                self.accounts[key].mode = str(default_mode).upper().strip() or "STANDARD"

        for key, value in mode_map.items():
            account_key = str(key).upper().strip()
            if account_key in self.accounts:
                self.accounts[account_key].mode = str(value).upper().strip() or "STANDARD"

        if primary_account is not None:
            requested = str(primary_account).upper().strip()
            if requested in self.accounts:
                self.primary_account_key = requested

        if not self.accounts.get(self.primary_account_key) or not self.accounts[self.primary_account_key].active:
            for key, account in self.accounts.items():
                if account.active:
                    self.primary_account_key = key
                    break

        self.accounts[self.primary_account_key].active = True

    def active_keys(self) -> list[str]:
        return [key for key, account in self.accounts.items() if account.active]

    def account_profile(self, account_key: str) -> dict:
        account = self.accounts.get(account_key)
        mode = account.mode if account else "STANDARD"
        return profile_for(account_key, mode)

    def primary_profile(self) -> dict:
        return self.account_profile(self.primary_account_key)

    def portfolio_profile(self, phase: str | None = None) -> dict:
        active = self.active_keys()
        profiles = [self.account_profile(key) for key in active]
        if not profiles:
            profiles = [self.primary_profile()]

        strict_daily_dd_pct = min(float(item.get("daily_dd_pct", 4.0)) for item in profiles)
        strict_max_dd_pct = min(float(item.get("max_dd_pct", 8.0)) for item in profiles)
        strict_risk_pct = min(profile_risk_pct(item, phase) for item in profiles)

        smallest = min(float(item.get("account_size", 50000.0)) for item in profiles)
        largest = max(float(item.get("account_size", 50000.0)) for item in profiles)

        return {
            "active_accounts": active,
            "strict_daily_dd_pct": strict_daily_dd_pct,
            "strict_max_dd_pct": strict_max_dd_pct,
            "strict_risk_pct": strict_risk_pct,
            "smallest_account_size": smallest,
            "largest_account_size": largest,
            "profiles": profiles,
        }

    def snapshot(self, phase: str | None = None) -> dict:
        active = self.active_keys()
        primary = self.primary_profile()
        portfolio = self.portfolio_profile(phase=phase)

        accounts = []
        for key, account in self.accounts.items():
            profile = self.account_profile(key)
            accounts.append({
                "account_key": key,
                "mode": account.mode,
                "active": bool(account.active),
                "profile": profile,
            })

        return {
            "primary_account": self.primary_account_key,
            "active_accounts": active,
            "primary_profile": primary,
            "portfolio": portfolio,
            "accounts": accounts,
        }
