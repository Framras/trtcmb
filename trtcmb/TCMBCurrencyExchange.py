from datetime import datetime
from typing import NamedTuple

import frappe
from frappe.utils import cint, flt, getdate

DEFAULT_BATCH_DAYS = 5
MAX_BATCH_DAYS = 30


class TCMBCurrencyExchange:
    doctype = "Currency Exchange"
    doctype_field_name = "exchange_rate"
    tcmb_date_key = "Tarih"
    tcmb_strip_key = "UNIXTIME"
    tcmb_date_format = "%d-%m-%Y"
    response_separator = "_"
    buying_code = "A"
    selling_code = "S"
    to_currency = "TRY"

    @classmethod
    def parse_tcmb_date(cls, value):
        if not value:
            return None
        if hasattr(value, "year"):
            return getdate(value)
        try:
            return getdate(datetime.strptime(str(value), cls.tcmb_date_format))
        except ValueError:
            return getdate(value, parse_day_first=True)

    @classmethod
    def commit_single_currency_exchange_rate(
        cls,
        tcmb_data: dict,
        enable_update: int,
        rate_options: "RateOptions | None" = None,
    ):
        exchange_rate_date = cls.parse_tcmb_date(tcmb_data.get(cls.tcmb_date_key))
        if not exchange_rate_date:
            return

        options = rate_options or default_rate_options()

        for key, raw_rate in tcmb_data.items():
            if key == cls.tcmb_date_key:
                continue

            key_list = str(key).split(cls.response_separator)
            if len(key_list) < 4:
                continue

            from_currency = key_list[2]
            flags = transaction_flags(key_list[3], options)
            if not flags:
                continue
            for_buying, for_selling = flags

            exchange_rate = flt(raw_rate)
            if exchange_rate <= 0:
                continue

            filters = {
                "date": exchange_rate_date,
                "from_currency": from_currency,
                "to_currency": cls.to_currency,
                "for_buying": for_buying,
                "for_selling": for_selling,
            }
            existing_name = frappe.db.exists(cls.doctype, filters)

            if existing_name:
                if enable_update != 1:
                    continue
                current_rate = flt(frappe.db.get_value(cls.doctype, existing_name, "exchange_rate"))
                if current_rate == exchange_rate:
                    continue
                frdoc = frappe.get_doc(cls.doctype, existing_name)
                frdoc.exchange_rate = exchange_rate
                frdoc.save(ignore_permissions=True)
            else:
                newdoc = frappe.new_doc(cls.doctype)
                newdoc.date = exchange_rate_date
                newdoc.from_currency = from_currency
                newdoc.to_currency = cls.to_currency
                newdoc.for_buying = for_buying
                newdoc.for_selling = for_selling
                newdoc.exchange_rate = exchange_rate
                newdoc.insert(ignore_permissions=True)


class RateOptions(NamedTuple):
    fetch_buying: int
    buying_for_buying: int
    buying_for_selling: int
    fetch_selling: int
    selling_for_buying: int
    selling_for_selling: int


def default_rate_options() -> RateOptions:
    """Buying rate for purchases, selling rate for sales."""
    return RateOptions(1, 1, 0, 1, 0, 1)


def normalize_batch_days(value) -> int:
    days = cint(value)
    if days < 1:
        return DEFAULT_BATCH_DAYS
    return min(days, MAX_BATCH_DAYS)


def normalize_rate_options(
    fetch_buying,
    buying_for_buying,
    buying_for_selling,
    fetch_selling,
    selling_for_buying,
    selling_for_selling,
) -> RateOptions:
    options = RateOptions(
        cint(fetch_buying),
        cint(buying_for_buying),
        cint(buying_for_selling),
        cint(fetch_selling),
        cint(selling_for_buying),
        cint(selling_for_selling),
    )
    if options == RateOptions(0, 0, 0, 0, 0, 0):
        return default_rate_options()
    return options


def transaction_flags(rate_code: str, options: RateOptions) -> tuple[int, int] | None:
    """Return Currency Exchange for_buying / for_selling flags for one TCMB rate."""
    if rate_code == TCMBCurrencyExchange.buying_code:
        if not options.fetch_buying:
            return None
        flags = (options.buying_for_buying, options.buying_for_selling)
    elif rate_code == TCMBCurrencyExchange.selling_code:
        if not options.fetch_selling:
            return None
        flags = (options.selling_for_buying, options.selling_for_selling)
    else:
        return None

    if flags == (0, 0):
        return None
    return flags


def rate_option_error(options: RateOptions) -> str | None:
    buying_flags = transaction_flags(TCMBCurrencyExchange.buying_code, options)
    selling_flags = transaction_flags(TCMBCurrencyExchange.selling_code, options)
    if options.fetch_buying and not buying_flags:
        return "Select a transaction type for the TCMB buying rate."
    if options.fetch_selling and not selling_flags:
        return "Select a transaction type for the TCMB selling rate."
    if not buying_flags and not selling_flags:
        return "Select at least one TCMB rate."
    if buying_flags and selling_flags:
        if buying_flags[0] and selling_flags[0]:
            return "Buying transactions can use only one TCMB rate."
        if buying_flags[1] and selling_flags[1]:
            return "Selling transactions can use only one TCMB rate."
    return None
