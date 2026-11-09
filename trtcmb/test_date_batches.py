from datetime import date, datetime
from unittest.mock import MagicMock, patch

from frappe.exceptions import DuplicateEntryError
from frappe.tests import UnitTestCase

from trtcmb.TCMBCurrencyExchange import TCMBCurrencyExchange

from trtcmb.dates import iter_date_batches, resolve_import_start
from trtcmb.recording import AnnouncedRate, first_working_day_rates, immediate_day_rates
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

    def test_year_start_is_used_only_when_no_start_date_was_supplied(self):
        self.assertEqual(resolve_import_start(None, date(2026, 11, 6)), date(2026, 1, 1))
        self.assertEqual(resolve_import_start(date(2026, 3, 15), date(2026, 11, 6)), date(2026, 3, 15))
        self.assertEqual(
            resolve_import_start(
                None,
                date(2026, 11, 6),
                last_updated=date(2026, 11, 5),
                incremental=True,
            ),
            date(2026, 11, 6),
        )

    def test_start_before_2_january_1950_uses_today(self):
        today = date(2026, 11, 6)
        self.assertEqual(resolve_import_start(date(1950, 1, 2), today), date(1950, 1, 2))
        self.assertEqual(resolve_import_start(date(1950, 1, 1), today), today)
        self.assertEqual(resolve_import_start(date(1949, 12, 31), today), today)
        self.assertEqual(resolve_import_start(date(1950, 1, 3), today), date(1950, 1, 3))
        self.assertEqual(
            resolve_import_start(
                date(1940, 1, 1),
                today,
                last_updated=date(1949, 12, 31),
                incremental=True,
            ),
            today,
        )

    def test_first_working_day_keeps_the_announced_rate_on_holidays_after_it(self):
        series = "TP_DK_USD_A_YTL"
        announcements = [
            AnnouncedRate(date(2026, 1, 1), {series: 40}),
            AnnouncedRate(date(2026, 1, 5), {series: 50}),
        ]

        recorded = dict(
            first_working_day_rates(announcements, date(2026, 1, 2), date(2026, 1, 5))
        )

        self.assertEqual(recorded[date(2026, 1, 2)][series], 40)
        self.assertEqual(recorded[date(2026, 1, 3)][series], 40)
        self.assertEqual(recorded[date(2026, 1, 4)][series], 40)
        self.assertEqual(recorded[date(2026, 1, 5)][series], 50)
        self.assertNotIn(date(2026, 1, 1), recorded)

    def test_immediate_day_keeps_the_announced_rate_on_its_own_day(self):
        series = "TP_DK_USD_A_YTL"
        announcements = [
            AnnouncedRate(date(2026, 10, 19), {series: 49.4463}),
            AnnouncedRate(date(2026, 10, 20), {series: 49.5523}),
            AnnouncedRate(date(2026, 10, 21), {series: 49.578}),
        ]

        recorded = dict(
            immediate_day_rates(announcements, date(2026, 10, 19), date(2026, 10, 21))
        )

        self.assertEqual(recorded[date(2026, 10, 19)][series], 49.4463)
        self.assertEqual(recorded[date(2026, 10, 20)][series], 49.5523)
        self.assertEqual(recorded[date(2026, 10, 21)][series], 49.578)

    def test_immediate_day_fills_empty_days_forward_and_backward(self):
        series = "TP_DK_USD_A_YTL"
        announcements = [
            AnnouncedRate(date(2026, 1, 2), {series: 41}),
            AnnouncedRate(date(2026, 1, 5), {series: 50}),
        ]

        recorded = dict(
            immediate_day_rates(announcements, date(2026, 1, 1), date(2026, 1, 5))
        )

        self.assertEqual(recorded[date(2026, 1, 1)][series], 41)
        self.assertEqual(recorded[date(2026, 1, 2)][series], 41)
        self.assertEqual(recorded[date(2026, 1, 3)][series], 41)
        self.assertEqual(recorded[date(2026, 1, 4)][series], 41)
        self.assertEqual(recorded[date(2026, 1, 5)][series], 50)

    def test_duplicate_insert_updates_the_existing_rate_instead_of_aborting(self):
        newdoc = MagicMock()
        newdoc.insert.side_effect = DuplicateEntryError
        existing = MagicMock()
        existing.exchange_rate = 40

        with (
            patch("trtcmb.TCMBCurrencyExchange.frappe.db.exists", side_effect=[None, "2026-01-05-USD-TRY-Buying"]),
            patch("trtcmb.TCMBCurrencyExchange.frappe.db.get_value", return_value=40),
            patch("trtcmb.TCMBCurrencyExchange.frappe.new_doc", return_value=newdoc),
            patch("trtcmb.TCMBCurrencyExchange.frappe.get_doc", return_value=existing),
        ):
            TCMBCurrencyExchange.commit_single_currency_exchange_rate(
                {"Tarih": "05-01-2026", "TP_DK_USD_A_YTL": 41},
                enable_update=1,
            )

        self.assertEqual(existing.exchange_rate, 41)
        existing.save.assert_called_once_with(ignore_permissions=True)

    def test_batch_size_defaults_when_unset_and_caps_at_thirty_days(self):
        self.assertEqual(normalize_batch_days(0), 5)
        self.assertEqual(normalize_batch_days(12), 12)
        self.assertEqual(normalize_batch_days(90), 30)
