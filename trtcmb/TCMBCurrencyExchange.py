from datetime import datetime

import frappe
from frappe.utils import flt, getdate


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
    def commit_single_currency_exchange_rate(cls, tcmb_data: dict, enable_update: int):
        exchange_rate_date = cls.parse_tcmb_date(tcmb_data.get(cls.tcmb_date_key))
        if not exchange_rate_date:
            return

        for key, raw_rate in tcmb_data.items():
            if key == cls.tcmb_date_key:
                continue

            key_list = str(key).split(cls.response_separator)
            if len(key_list) < 4:
                continue

            from_currency = key_list[2]
            for_selling = 1 if key_list[3] == cls.selling_code else 0
            for_buying = 1 if key_list[3] == cls.buying_code else 0
            if not for_buying and not for_selling:
                continue

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
