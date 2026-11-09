from datetime import date

from frappe.tests import UnitTestCase

from trtcmb.bulletin import (
    apply_strategy_empty_fill,
    bulletin_rates_for_currencies,
    bulletin_url,
    fill_empty_days_from_bulletin,
    parse_bulletin_xml,
    resolve_bulletin_series,
)
from trtcmb.dates import is_business_day, previous_business_day
from trtcmb.recording import AnnouncedRate, first_working_day_rates, immediate_day_rates

SAMPLE_BULLETIN = """<?xml version="1.0" encoding="UTF-8"?>
<Tarih_Date Tarih="16.10.2026" Date="10/16/2026" Bulten_No="2026/196">
	<Currency CrossOrder="0" Kod="USD" CurrencyCode="USD">
		<Unit>1</Unit>
		<ForexBuying>49.3573</ForexBuying>
		<ForexSelling>49.4463</ForexSelling>
		<BanknoteBuying>49.3228</BanknoteBuying>
		<BanknoteSelling>49.5204</BanknoteSelling>
	</Currency>
	<Currency CrossOrder="9" Kod="EUR" CurrencyCode="EUR">
		<Unit>1</Unit>
		<ForexBuying>55.5179</ForexBuying>
		<ForexSelling>55.6180</ForexSelling>
		<BanknoteBuying>55.4791</BanknoteBuying>
		<BanknoteSelling>55.7014</BanknoteSelling>
	</Currency>
	<Currency CrossOrder="11" Kod="JPY" CurrencyCode="JPY">
		<Unit>100</Unit>
		<ForexBuying>31.4000</ForexBuying>
		<ForexSelling>31.6000</ForexSelling>
		<BanknoteBuying>31.0000</BanknoteBuying>
		<BanknoteSelling>32.0000</BanknoteSelling>
	</Currency>
</Tarih_Date>
"""

PRE_2003_BULLETIN = """<?xml version="1.0" encoding="UTF-8"?>
<Tarih_Date Tarih="04.12.1998" Date="12/04/1998">
	<Currency CrossOrder="0" Kod="USD" CurrencyCode="USD">
		<Unit>1</Unit>
		<ForexBuying>301670</ForexBuying>
		<ForexSelling>302210</ForexSelling>
	</Currency>
</Tarih_Date>
"""

CURRENCIES = [
    {"name": "EUR", "buying_series": "TP.DK.EUR.A", "selling_series": "TP.DK.EUR.S"},
    {"name": "USD", "buying_series": "TP.DK.USD.A", "selling_series": "TP.DK.USD.S"},
]
SERIES = "TP_DK_EUR_S"


class TestBulletin(UnitTestCase):
    def test_bulletin_url_uses_year_month_and_day_month_year(self):
        self.assertEqual(
            bulletin_url(date(2026, 10, 16)),
            "https://www.tcmb.gov.tr/kurlar/202610/16102026.xml",
        )

    def test_parse_uses_forex_not_banknote_and_divides_by_unit(self):
        parsed = parse_bulletin_xml(SAMPLE_BULLETIN, date(2026, 10, 16))
        self.assertEqual(parsed["EUR"]["S"], 55.6180)
        self.assertEqual(parsed["EUR"]["A"], 55.5179)
        self.assertEqual(parsed["USD"]["S"], 49.4463)
        self.assertAlmostEqual(parsed["JPY"]["S"], 0.316)
        self.assertAlmostEqual(parsed["JPY"]["A"], 0.314)

    def test_parse_allows_missing_bulletin_number_before_2003(self):
        parsed = parse_bulletin_xml(PRE_2003_BULLETIN, date(1998, 12, 4))
        self.assertEqual(parsed["USD"]["A"], 301670)
        self.assertEqual(parsed["USD"]["S"], 302210)

    def test_parse_rejects_wrong_date(self):
        with self.assertRaises(Exception):
            parse_bulletin_xml(SAMPLE_BULLETIN, date(2026, 10, 17))

    def test_bulletin_maps_to_evds_series_keys(self):
        parsed = parse_bulletin_xml(SAMPLE_BULLETIN, date(2026, 10, 16))
        mapped = bulletin_rates_for_currencies(parsed, CURRENCIES)
        self.assertEqual(mapped["TP_DK_EUR_S"], 55.6180)
        self.assertEqual(mapped["TP_DK_EUR_A"], 55.5179)
        self.assertEqual(mapped["TP_DK_USD_S"], 49.4463)

    def test_previous_business_day_skips_weekend(self):
        self.assertTrue(is_business_day(date(2026, 10, 16)))
        self.assertFalse(is_business_day(date(2026, 10, 17)))
        self.assertEqual(previous_business_day(date(2026, 10, 17)), date(2026, 10, 16))
        self.assertEqual(previous_business_day(date(2026, 10, 19)), date(2026, 10, 16))

    def test_first_working_day_keeps_previous_evds_on_empty_days(self):
        announcements = [
            AnnouncedRate(date(2026, 10, 15), {SERIES: 55.3027}),
            AnnouncedRate(date(2026, 10, 16), {SERIES: 55.4110}),
            AnnouncedRate(date(2026, 10, 19), {SERIES: 55.6180}),
        ]
        recorded = dict(first_working_day_rates(announcements, date(2026, 10, 16), date(2026, 10, 19)))
        self.assertEqual(recorded[date(2026, 10, 16)][SERIES], 55.4110)
        self.assertEqual(recorded[date(2026, 10, 17)][SERIES], 55.4110)
        self.assertEqual(recorded[date(2026, 10, 18)][SERIES], 55.4110)
        self.assertEqual(recorded[date(2026, 10, 19)][SERIES], 55.6180)

    def test_immediate_day_leaves_empty_days_for_bulletin(self):
        announcements = [
            AnnouncedRate(date(2026, 10, 16), {SERIES: 55.4110}),
            AnnouncedRate(date(2026, 10, 19), {SERIES: 55.6180}),
        ]
        recorded = dict(immediate_day_rates(announcements, date(2026, 10, 16), date(2026, 10, 19)))
        self.assertEqual(recorded[date(2026, 10, 16)][SERIES], 55.4110)
        self.assertEqual(recorded[date(2026, 10, 19)][SERIES], 55.6180)
        self.assertNotIn(date(2026, 10, 17), recorded)
        self.assertNotIn(date(2026, 10, 18), recorded)

    def test_immediate_bulletin_fill_uses_friday_bulletin_on_weekend(self):
        announcements = [
            AnnouncedRate(date(2026, 10, 16), {SERIES: 55.4110}),
            AnnouncedRate(date(2026, 10, 19), {SERIES: 55.6180}),
            AnnouncedRate(date(2026, 10, 20), {SERIES: 55.5676}),
            AnnouncedRate(date(2026, 10, 21), {SERIES: 55.6191}),
        ]
        window = (date(2026, 10, 16), date(2026, 10, 21))
        recorded = immediate_day_rates(announcements, *window)
        covered = {SERIES: date(2026, 10, 16)}
        calls = []

        def fetch(for_date, _currency_list):
            calls.append(getdate_safe(for_date))
            if getdate_safe(for_date) == date(2026, 10, 16):
                return {SERIES: 55.6180}
            return None

        filled = dict(
            fill_empty_days_from_bulletin(recorded, CURRENCIES, *window, covered, fetch_series=fetch)
        )
        self.assertEqual(filled[date(2026, 10, 16)][SERIES], 55.4110)
        self.assertEqual(filled[date(2026, 10, 17)][SERIES], 55.6180)
        self.assertEqual(filled[date(2026, 10, 18)][SERIES], 55.6180)
        self.assertEqual(filled[date(2026, 10, 19)][SERIES], 55.6180)
        self.assertIn(date(2026, 10, 16), calls)

    def test_bulletin_walks_back_when_friday_is_missing(self):
        """01.05.2026 Friday holiday: Sat/Sun use Thursday 30.04 bulletin."""
        announcements = [
            AnnouncedRate(date(2026, 4, 30), {SERIES: 48.0}),
            AnnouncedRate(date(2026, 5, 4), {SERIES: 49.0}),
        ]
        window = (date(2026, 5, 2), date(2026, 5, 3))
        recorded = immediate_day_rates(announcements, *window)
        covered = {SERIES: date(2026, 4, 30)}
        calls = []

        def fetch(for_date, _currency_list):
            day = getdate_safe(for_date)
            calls.append(day)
            if day == date(2026, 5, 1):
                return None
            if day == date(2026, 4, 30):
                return {SERIES: 47.5}
            return None

        filled = dict(
            fill_empty_days_from_bulletin(recorded, CURRENCIES, *window, covered, fetch_series=fetch)
        )
        self.assertEqual(filled[date(2026, 5, 2)][SERIES], 47.5)
        self.assertEqual(filled[date(2026, 5, 3)][SERIES], 47.5)
        self.assertEqual(calls[0], date(2026, 5, 1))
        self.assertIn(date(2026, 4, 30), calls)

    def test_bulletin_fallback_uses_previous_evds_rate_when_no_bulletin(self):
        announcements = [
            AnnouncedRate(date(2026, 10, 16), {SERIES: 55.4110}),
            AnnouncedRate(date(2026, 10, 19), {SERIES: 55.6180}),
        ]
        window = (date(2026, 10, 16), date(2026, 10, 19))
        recorded = immediate_day_rates(announcements, *window)
        covered = {SERIES: date(2026, 10, 16)}

        def fetch(_for_date, _currency_list):
            return None

        filled = dict(
            fill_empty_days_from_bulletin(recorded, CURRENCIES, *window, covered, fetch_series=fetch)
        )
        self.assertEqual(filled[date(2026, 10, 17)][SERIES], 55.4110)
        self.assertEqual(filled[date(2026, 10, 18)][SERIES], 55.4110)
        self.assertEqual(filled[date(2026, 10, 19)][SERIES], 55.6180)

    def test_strategy_dispatch_skips_bulletin_for_first_working_day(self):
        announcements = [
            AnnouncedRate(date(2026, 10, 16), {SERIES: 55.4110}),
            AnnouncedRate(date(2026, 10, 19), {SERIES: 55.6180}),
        ]
        recorded = first_working_day_rates(announcements, date(2026, 10, 16), date(2026, 10, 19))
        covered = {SERIES: date(2026, 10, 16)}
        calls = []

        def fetch(for_date, _currency_list):
            calls.append(for_date)
            return {SERIES: 99.0}

        result = dict(
            apply_strategy_empty_fill(
                recorded,
                CURRENCIES,
                date(2026, 10, 16),
                date(2026, 10, 19),
                covered,
                "First Working Day",
                fetch_series=fetch,
            )
        )
        self.assertEqual(calls, [])
        self.assertEqual(result[date(2026, 10, 17)][SERIES], 55.4110)

    def test_resolve_bulletin_series_walks_back_ten_business_days_max(self):
        calls = []

        def fetch(for_date, _currency_list):
            calls.append(getdate_safe(for_date))
            return None

        found = resolve_bulletin_series(
            date(2026, 5, 1), CURRENCIES, fetch_series=fetch, max_lookback=3
        )
        self.assertEqual(found, {})
        self.assertEqual(len(calls), 3)


def getdate_safe(value):
    from frappe.utils import getdate

    return getdate(value)
