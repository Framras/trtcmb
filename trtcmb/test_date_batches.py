from datetime import date, datetime

from frappe.tests import UnitTestCase

from trtcmb.TCMBConnection import iter_date_batches
from trtcmb.tasks import company_import_is_due
from trtcmb.TCMBCurrencyExchange import (
    normalize_batch_days,
    normalize_rate_options,
    rate_option_error,
    transaction_flags,
)


class TestTCMBDateBatches(UnitTestCase):
    def test_five_day_batches_cover_the_full_requested_range(self):
        batches = iter_date_batches(date(2026, 1, 1), date(2026, 1, 12), batch_days=5)

        self.assertEqual(
            batches,
            [
                (date(2026, 1, 1), date(2026, 1, 5)),
                (date(2026, 1, 6), date(2026, 1, 10)),
                (date(2026, 1, 11), date(2026, 1, 12)),
            ],
        )

    def test_single_day_range_is_one_batch(self):
        batches = iter_date_batches(date(2026, 11, 3), date(2026, 11, 3), batch_days=5)
        self.assertEqual(batches, [(date(2026, 11, 3), date(2026, 11, 3))])

    def test_each_rate_uses_its_own_transaction_checkboxes(self):
        options = normalize_rate_options(1, 1, 1, 1, 0, 0)
        self.assertEqual(transaction_flags("A", options), (1, 1))
        self.assertIsNone(transaction_flags("S", options))

    def test_same_transaction_type_cannot_use_both_rates(self):
        options = normalize_rate_options(1, 1, 0, 1, 1, 1)
        self.assertEqual(rate_option_error(options), "Buying transactions can use only one TCMB rate.")

    def test_company_import_runs_after_its_daily_time_until_today_is_imported(self):
        now = datetime(2026, 11, 3, 1, 0)
        self.assertFalse(company_import_is_due(now, "02:00:00", None))
        self.assertTrue(company_import_is_due(now, "00:58:00", date(2026, 11, 2)))
        self.assertFalse(company_import_is_due(now, "00:58:00", date(2026, 11, 3)))

    def test_batch_size_defaults_when_unset_and_caps_at_thirty_days(self):
        self.assertEqual(normalize_batch_days(0), 5)
        self.assertEqual(normalize_batch_days(12), 12)
        self.assertEqual(normalize_batch_days(90), 30)
