import unittest

from spend_rules import APPROVE, AUTOMATIC, BLOCK, Purchase, SpendRules, DEFAULT_RULES, rows


class TestSpendRules(unittest.TestCase):
    def test_allowed_purchase_inside_both_caps_is_automatic(self):
        got = DEFAULT_RULES.evaluate(Purchase("API Foundry", "software", 1200), 2000)
        self.assertEqual(got.outcome, AUTOMATIC)
        self.assertFalse(got.needs_approval)

    def test_merchant_limit_sends_purchase_to_owner(self):
        got = DEFAULT_RULES.evaluate(Purchase("API Foundry", "software", 4800), 0)
        self.assertEqual(got.outcome, APPROVE)
        self.assertIn("merchant automatic limit", got.reasons[0])

    def test_daily_limit_sends_purchase_to_owner(self):
        got = DEFAULT_RULES.evaluate(Purchase("Developer Tools", "software", 2000), 6000)
        self.assertEqual(got.outcome, APPROVE)
        self.assertTrue(any("daily automatic limit" in r for r in got.reasons))

    def test_unknown_merchant_sends_purchase_to_owner(self):
        got = DEFAULT_RULES.evaluate(Purchase("New Vendor", "data", 100), 0)
        self.assertEqual(got.outcome, APPROVE)
        self.assertIn("No automatic limit", got.reasons[0])

    def test_disallowed_category_is_blocked_before_paypal(self):
        got = DEFAULT_RULES.evaluate(Purchase("API Foundry", "collectibles", 100), 0)
        self.assertEqual(got.outcome, BLOCK)

    def test_exact_caps_remain_automatic(self):
        got = DEFAULT_RULES.evaluate(Purchase("API Foundry", "software", 3000), 4500)
        self.assertEqual(got.outcome, AUTOMATIC)

    def test_invalid_money_is_refused(self):
        with self.assertRaises(ValueError):
            DEFAULT_RULES.evaluate(Purchase("API Foundry", "software", 0), 0)

    def test_monthly_plan_uses_separate_cap_and_needs_owner(self):
        got = DEFAULT_RULES.evaluate(Purchase("Developer Tools", "software", 2400, recurring=True), 7400)
        self.assertEqual(got.outcome, APPROVE)
        self.assertIn("EUR 60.00", got.reasons[0])
        self.assertNotIn("daily", got.reasons[0].lower())

    def test_monthly_plan_over_cap_is_blocked(self):
        got = DEFAULT_RULES.evaluate(Purchase("Developer Tools", "software", 6100, recurring=True), 0)
        self.assertEqual(got.outcome, BLOCK)
        self.assertIn("EUR 60.00", got.reasons[0])

    def test_rule_reasons_show_eur_not_raw_cents(self):
        merchant = DEFAULT_RULES.evaluate(Purchase("API Foundry", "software", 4800), 0)
        daily = DEFAULT_RULES.evaluate(Purchase("Developer Tools", "software", 2000), 6000)
        self.assertTrue(all(" cents" not in reason for reason in merchant.reasons + daily.reasons))

    def test_rows_show_all_three_rule_types(self):
        labels = [r["rule"] for r in rows()]
        self.assertIn("Category allowlist", labels)
        self.assertIn("Daily automatic limit", labels)
        self.assertIn("Monthly plan limit", labels)
        self.assertIn("Renewal reminder", labels)
        self.assertTrue(any("automatic limit" in label and label != "Daily automatic limit" for label in labels))

    def test_invalid_configuration_is_refused(self):
        with self.assertRaises(ValueError):
            SpendRules(frozenset({"software"}), {"API": 0}, 100)


if __name__ == "__main__":
    unittest.main()
