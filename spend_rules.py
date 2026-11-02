"""Deterministic rules for deciding whether an agent purchase needs a person.

The module has no PayPal or model dependency. Amounts are integer euro cents.
Categories outside the allowlist are blocked. Allowed purchases are automatic only
while both the merchant and daily automatic-spend limits remain intact. Monthly
plans use a separate hard cap and always require owner approval before they start.
"""
from dataclasses import dataclass
from typing import Mapping


BLOCK = "blocked"
APPROVE = "needs_approval"
AUTOMATIC = "automatic"


@dataclass(frozen=True)
class Purchase:
    merchant: str
    category: str
    cents: int
    recurring: bool = False


@dataclass(frozen=True)
class Decision:
    outcome: str
    reasons: tuple[str, ...]

    @property
    def needs_approval(self):
        return self.outcome == APPROVE


@dataclass(frozen=True)
class SpendRules:
    allowed_categories: frozenset[str]
    merchant_auto_caps: Mapping[str, int]
    daily_auto_cap: int
    subscription_monthly_cap: int = 6000

    def __post_init__(self):
        if self.daily_auto_cap <= 0:
            raise ValueError("daily_auto_cap must be positive integer cents")
        if type(self.subscription_monthly_cap) is not int or self.subscription_monthly_cap <= 0:
            raise ValueError("subscription_monthly_cap must be positive integer cents")
        if any(type(v) is not int or v <= 0 for v in self.merchant_auto_caps.values()):
            raise ValueError("merchant caps must be positive integer cents")
        if not self.allowed_categories:
            raise ValueError("at least one category must be allowed")

    def evaluate(self, purchase: Purchase, automatic_spend_today: int) -> Decision:
        if type(purchase.cents) is not int or purchase.cents <= 0:
            raise ValueError("purchase cents must be a positive integer")
        if type(automatic_spend_today) is not int or automatic_spend_today < 0:
            raise ValueError("automatic_spend_today must be a non-negative integer")

        category = purchase.category.strip().casefold()
        merchant = purchase.merchant.strip().casefold()
        allowed = {c.strip().casefold() for c in self.allowed_categories}
        caps = {k.strip().casefold(): v for k, v in self.merchant_auto_caps.items()}

        if category not in allowed:
            return Decision(BLOCK, (f'Category "{purchase.category}" is not allowed.',))

        if purchase.recurring:
            if purchase.cents > self.subscription_monthly_cap:
                return Decision(
                    BLOCK,
                    (f'Monthly plan exceeds the subscription cap of EUR {self.subscription_monthly_cap / 100:.2f}.',),
                )
            return Decision(
                APPROVE,
                (f'New monthly plan within the EUR {self.subscription_monthly_cap / 100:.2f} cap. Owner approval is required.',),
            )

        reasons = []
        merchant_cap = caps.get(merchant)
        if merchant_cap is None:
            reasons.append(f'No automatic limit exists for merchant "{purchase.merchant}".')
        elif purchase.cents > merchant_cap:
            reasons.append(f'Purchase exceeds the merchant automatic limit of EUR {merchant_cap / 100:.2f}.')

        if automatic_spend_today + purchase.cents > self.daily_auto_cap:
            reasons.append(f'Purchase would exceed the daily automatic limit of EUR {self.daily_auto_cap / 100:.2f}.')

        if reasons:
            return Decision(APPROVE, tuple(reasons))
        return Decision(AUTOMATIC, ("All automatic-spend rules passed.",))


DEFAULT_RULES = SpendRules(
    allowed_categories=frozenset({"software", "data", "infrastructure"}),
    merchant_auto_caps={
        "API Foundry": 3000,
        "Cloud Compute": 5000,
        "Developer Tools": 2500,
    },
    daily_auto_cap=7500,
)


def rows(rules=DEFAULT_RULES):
    """Serializable rows for the UI and review card."""
    out = [
        {"rule": "Category allowlist", "value": ", ".join(sorted(rules.allowed_categories)),
         "effect": "Anything else is blocked before PayPal."},
    ]
    out.extend({"rule": f"{merchant} automatic limit", "value": f"EUR {cents / 100:.2f}",
                "effect": "A larger purchase goes to the owner."}
               for merchant, cents in rules.merchant_auto_caps.items())
    out.append({"rule": "Daily automatic limit", "value": f"EUR {rules.daily_auto_cap / 100:.2f}",
                "effect": "The next purchase goes to the owner when this would be exceeded."})
    out.append({"rule": "Monthly plan limit", "value": f"EUR {rules.subscription_monthly_cap / 100:.2f} / month",
                "effect": "New plans need approval. Plans above this cap are blocked."})
    out.append({"rule": "Renewal reminder", "value": "3 days before renewal",
                "effect": "The owner can cancel the plan in one tap before the next renewal."})
    return out
