"""Imports stay resumable, and last_updated moves only when a day was recorded."""

from datetime import date
from unittest.mock import MagicMock, patch
from contextlib import ExitStack

from frappe.tests import UnitTestCase
from frappe.utils import getdate

from trtcmb.dates import EARLIEST_TCMB_DATE, calendar_days
from trtcmb.recording import rates_for_rule
from trtcmb.TCMBConnection import LOOKBACK_LIMIT_DAYS, TCMBConnection, TCMBRateNotFound
from trtcmb.TCMBCurrencyExchange import default_rate_options

SERIES = "TP_DK_USD_A_YTL"
NULL_RATE = object()


class TestImportSafety(UnitTestCase):
    def test_last_updated_advances_only_to_last_recorded_day(self):
        # 1950-01-03 with an empty EVDS response, including the anchor day.
        conn, updates = self._connection(start=date(1950, 1, 3), today=date(1950, 1, 7))
        conn.get_exchange_rates = lambda _currency_list, _start, _end: ([], 0)
        with self._fixed_today(date(1950, 1, 7)), self.assertRaises(TCMBRateNotFound):
            conn.get_exchange_rates_for_enabled_currencies(incremental=False)
        self.assertEqual(updates, [])
        self.assertIsNone(conn.last_updated)

    def test_empty_chunk_does_not_advance_last_updated(self):
        # Anchor exists, but every weekday chunk comes back empty.
        table = {date(2026, 1, 4): 10}
        conn, updates = self._connection(start=date(2026, 1, 5), today=date(2026, 1, 7), batch_days=1)
        logger = MagicMock()
        with (
            self._fixed_today(date(2026, 1, 7)),
            self._feed(conn, table),
            patch("trtcmb.TCMBConnection.frappe.logger", return_value=logger),
            self.assertRaises(Exception) as caught,
        ):
            conn.get_exchange_rates_for_enabled_currencies(incremental=False)
        self.assertNotIsInstance(caught.exception, TCMBRateNotFound)
        self.assertIn("Test Co", str(caught.exception))
        self.assertEqual(updates, [])
        self.assertGreaterEqual(logger.warning.call_count, 3)

    def test_first_date_is_valid_start_and_anchor(self):
        table = {date(1950, 1, 2): 4, date(1950, 1, 3): NULL_RATE}
        conn, updates = self._connection(start=date(1950, 1, 3), today=date(1950, 1, 3), batch_days=1)
        written = []
        with self._fixed_today(date(1950, 1, 3)), self._feed(conn, table), self._capture(conn, written):
            last = conn.get_exchange_rates_for_enabled_currencies(incremental=False)
        self.assertEqual(last, date(1950, 1, 3))
        self.assertEqual(written, [date(1950, 1, 3)])
        self.assertEqual(updates, [date(1950, 1, 3)])

        start_on_boundary, _updates = self._connection(start=EARLIEST_TCMB_DATE, today=date(1950, 1, 2))
        boundary_written = []
        with (
            self._fixed_today(date(1950, 1, 2)),
            self._feed(start_on_boundary, {date(1950, 1, 2): 4}),
            self._capture(start_on_boundary, boundary_written),
        ):
            start_on_boundary.get_exchange_rates_for_enabled_currencies(incremental=False)
        self.assertEqual(boundary_written, [date(1950, 1, 2)])

    def test_carried_rate_is_kept_per_series(self):
        usd = "TP_DK_USD_A_YTL"
        eur = "TP_DK_EUR_A_YTL"
        table = {
            date(2025, 12, 31): {usd: 42.90, eur: 50.50},
            date(2026, 1, 2): {usd: 42.92, eur: 50.37},
            date(2026, 1, 5): {eur: 50.38},
            date(2026, 1, 6): NULL_RATE,
        }
        conn, _updates = self._connection(start=date(2026, 1, 1), today=date(2026, 1, 6), batch_days=1)
        written = {}
        with self._fixed_today(date(2026, 1, 6)), self._feed(conn, table), self._capture_rates(conn, written):
            conn.get_exchange_rates_for_enabled_currencies(incremental=False)
        self.assertEqual(written[date(2026, 1, 6)][usd], 42.92)
        self.assertEqual(written[date(2026, 1, 6)][eur], 50.38)

    def test_missing_series_day_fails_the_run(self):
        table = {date(1950, 1, 2): 4, date(1950, 1, 3): NULL_RATE}
        conn, updates = self._connection(start=date(1950, 1, 3), today=date(1950, 1, 3), batch_days=1)

        def drop_rates(*args, **kwargs):
            return [(day, {}) for day, _rates in rates_for_rule(*args, **kwargs)]

        with (
            self._fixed_today(date(1950, 1, 3)),
            self._feed(conn, table),
            self._capture(conn, []),
            patch("trtcmb.TCMBConnection.rates_for_rule", side_effect=drop_rates),
            self.assertRaises(Exception) as caught,
        ):
            conn.get_exchange_rates_for_enabled_currencies(incremental=False)
        self.assertIn("did not record", str(caught.exception))
        self.assertEqual(updates, [])

    def test_anchor_missing_but_range_has_data_proceeds(self):
        eur_start = self._run(date(1999, 1, 4), date(1999, 1, 4), {date(1999, 1, 4): 1})
        self.assertEqual(eur_start, [date(1999, 1, 4)])

        discovered = self._run(
            date(1998, 12, 28),
            date(1999, 1, 4),
            {date(1999, 1, 4): 1},
            batch_days=1,
        )
        self.assertEqual(discovered, [date(1999, 1, 4)])

        conn, _updates = self._connection(start=date(1990, 1, 1), today=date(1990, 12, 31), batch_days=5)
        calls = []

        def fetch(_currency_list, start, end):
            calls.append((getdate(start), getdate(end)))
            return [], 0

        conn.get_exchange_rates = fetch
        with self._fixed_today(date(1990, 12, 31)), self.assertRaises(TCMBRateNotFound):
            conn.get_exchange_rates_for_enabled_currencies(incremental=False)
        self.assertLessEqual(len(calls), LOOKBACK_LIMIT_DAYS + 1 + LOOKBACK_LIMIT_DAYS)
        self.assertLess(len(calls), 80)

    def test_import_resumes_after_interruption(self):
        today = date(1960, 1, 20)
        table = _weekday_rates(date(1960, 1, 3), today)
        first, updates = self._connection(start=date(1960, 1, 4), today=today, batch_days=5)
        seen = {"batches": 0}

        def fetch(_currency_list, start, end):
            start, end = getdate(start), getdate(end)
            if start != end:
                seen["batches"] += 1
                if seen["batches"] > 1:
                    raise RuntimeError("killed")
            return _rows(start, end, table)

        first.get_exchange_rates = fetch
        with self._fixed_today(today), self._capture(first, []), self.assertRaises(RuntimeError):
            first.get_exchange_rates_for_enabled_currencies(incremental=False)
        self.assertEqual(updates, [date(1960, 1, 8)])

        resumed_days = self._run(date(1960, 1, 4), today, table, last_updated=date(1960, 1, 8), incremental=True)
        self.assertEqual(resumed_days[0], date(1960, 1, 9))
        self.assertEqual(resumed_days[-1], today)

    def test_deep_backfill_completes_across_runs(self):
        today = date(1960, 2, 5)
        start = date(1960, 1, 4)
        table = _weekday_rates(date(1960, 1, 3), today)
        expected = self._run(start, today, table)
        pieces = []
        last_updated = None
        for _attempt in range(6):
            conn, updates = self._connection(
                start=start, today=today, batch_days=5, last_updated=last_updated
            )
            seen = {"batches": 0}

            def fetch(_currency_list, chunk_start, chunk_end, seen=seen):
                chunk_start, chunk_end = getdate(chunk_start), getdate(chunk_end)
                if chunk_start != chunk_end:
                    seen["batches"] += 1
                    if seen["batches"] > 2:
                        raise RuntimeError("killed")
                return _rows(chunk_start, chunk_end, table)

            conn.get_exchange_rates = fetch
            caught = []
            try:
                with self._fixed_today(today), self._capture(conn, caught):
                    conn.get_exchange_rates_for_enabled_currencies(incremental=bool(last_updated))
            except RuntimeError:
                self.assertTrue(updates)
            else:
                pieces.extend(caught)
                break
            pieces.extend(caught)
            last_updated = updates[-1]
        self.assertEqual(pieces[0], expected[0])
        self.assertEqual(pieces[-1], expected[-1])
        self.assertEqual(len(pieces), len(set(pieces)))
        self.assertEqual(set(pieces), set(expected))

    def test_manual_rerun_over_an_older_range_does_not_move_last_updated_backwards(self):
        table = _weekday_rates(date(2026, 1, 4), date(2026, 1, 8))
        conn, updates = self._connection(
            start=date(2026, 1, 5),
            today=date(2026, 1, 8),
            last_updated=date(2026, 1, 10),
        )
        with self._fixed_today(date(2026, 1, 8)), self._feed(conn, table), self._capture(conn, []):
            conn.get_exchange_rates_for_enabled_currencies(incremental=False)
        self.assertEqual(updates, [])
        self.assertEqual(conn.last_updated, date(2026, 1, 10))

    def test_weekend_coverage_is_unchanged_for_both_recording_rules(self):
        friday = date(2026, 1, 9)
        monday = date(2026, 1, 12)
        table = {date(2026, 1, 8): 7, friday: 9, monday: 11}
        for rule, saturday_rate in (("First Working Day", 9), ("Immediate Day", 9)):
            written = {}
            conn, _updates = self._connection(
                start=friday, today=monday, batch_days=5, rule=rule
            )
            with self._fixed_today(monday), self._feed(conn, table), self._capture_rates(conn, written):
                conn.get_exchange_rates_for_enabled_currencies(incremental=False)
            self.assertEqual(written[date(2026, 1, 10)][SERIES], saturday_rate)
            self.assertEqual(written[date(2026, 1, 11)][SERIES], saturday_rate)
        whole = rates_for_rule(
            "First Working Day",
            _announcements(table),
            friday,
            monday,
        )
        recorded = {}
        conn, _updates = self._connection(start=friday, today=monday, batch_days=5)
        with self._fixed_today(monday), self._feed(conn, table), self._capture_rates(conn, recorded):
            conn.get_exchange_rates_for_enabled_currencies(incremental=False)
        self.assertEqual(recorded, dict(whole))

    def test_boundary_error_says_before_2_january_1950(self):
        conn, _updates = self._connection(start=date(1950, 1, 2), today=date(1950, 1, 2))
        with self.assertRaises(TCMBRateNotFound) as caught:
            conn.retrieve_announced_rate([], date(1950, 1, 1))
        message = str(caught.exception)
        self.assertIn("before", message)
        self.assertNotIn("on or before", message)

    def _run(self, start, today, table, last_updated=None, incremental=False, batch_days=5):
        conn, _updates = self._connection(
            start=start, today=today, batch_days=batch_days, last_updated=last_updated
        )
        written = []
        with self._fixed_today(today), self._feed(conn, table), self._capture(conn, written):
            conn.get_exchange_rates_for_enabled_currencies(incremental=incremental)
        return written

    def _connection(self, start, today, batch_days=5, last_updated=None, rule="First Working Day"):
        conn = TCMBConnection.__new__(TCMBConnection)
        conn.company = "Test Co"
        conn.enable = 1
        conn.a_day = 1
        conn.batch_days = batch_days
        conn.batch_pause_seconds = 1
        conn.rate_recording_rule = rule
        conn.rate_options = default_rate_options()
        conn.enable_update = 1
        conn.last_updated = last_updated
        conn.start_date = start
        conn._today = today
        updates = []

        def set_value(_doctype, _name, field, value):
            if field == "last_updated":
                updates.append(getdate(value))

        conn._set_value = set_value
        return conn, updates

    def _fixed_today(self, today):
        stack = ExitStack()
        stack.enter_context(patch("trtcmb.TCMBConnection.nowdate", return_value=today))
        stack.enter_context(
            patch(
                "trtcmb.TCMBConnection.TCMBCurrency.get_list_of_enabled_currencies",
                return_value=[_usd()],
            )
        )
        return stack

    def _feed(self, conn, table):
        def fetch(_currency_list, start, end):
            return _rows(start, end, table)

        conn.get_exchange_rates = fetch
        return patch("trtcmb.TCMBConnection.TCMBCurrency.get_list_of_enabled_currencies", return_value=[_usd()])

    def _capture(self, conn, written):
        def record(dated_rates):
            days = []
            for day, rates in dated_rates:
                if not rates:
                    continue
                days.append(getdate(day))
            written.extend(days)
            return sorted(days)

        conn.record_exchange_rates = record
        return patch("trtcmb.TCMBConnection.frappe.db.set_value", side_effect=conn._set_value)

    def _capture_rates(self, conn, written):
        def record(dated_rates):
            days = []
            for day, rates in dated_rates:
                if not rates:
                    continue
                day = getdate(day)
                written[day] = dict(rates)
                days.append(day)
            return sorted(days)

        conn.record_exchange_rates = record
        return patch("trtcmb.TCMBConnection.frappe.db.set_value", side_effect=conn._set_value)


def _usd():
    return {"name": "USD", "buying_series": "TP.DK.USD.A.YTL", "selling_series": "TP.DK.USD.S.YTL"}


def _weekday_rates(start, end):
    table = {}
    for day in calendar_days(start, end):
        if day.weekday() < 5 and day >= EARLIEST_TCMB_DATE:
            table[day] = 1 + (day - date(1950, 1, 2)).days / 1000
    return table


def _rows(start, end, table):
    rows = []
    for day in calendar_days(start, end):
        rate = table.get(getdate(day))
        if rate is None:
            continue
        stamped = getdate(day).strftime("%d-%m-%Y")
        if isinstance(rate, dict):
            row = {"Tarih": stamped}
            for key, value in rate.items():
                row[key] = None if value is NULL_RATE else value
            rows.append(row)
            continue
        rows.append({"Tarih": stamped, SERIES: None if rate is NULL_RATE else rate})
    return rows, len(rows)


def _announcements(table):
    from trtcmb.recording import AnnouncedRate

    found = []
    for day in sorted(table):
        rate = table[day]
        if rate is NULL_RATE or not rate:
            continue
        found.append(AnnouncedRate(day, {SERIES: rate}))
    return found
