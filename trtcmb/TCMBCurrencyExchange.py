import frappe
import datetime

from frappe.utils.data import flt


class TCMBCurrencyExchange:
    doctype = "Currency Exchange"
    tcmb_date_key = "Tarih"
    tcmb_date_format = "%d-%m-%Y"
    a_day = datetime.timedelta(days=1)
    buying_code = "A"
    selling_code = "S"
    to_currency = "TRY"
    strip_key = "UNIXTIME"

    @classmethod
    def commit_single_exchange_rate(cls, tcmb_data: dict):
        exchange_rate_date = datetime.datetime.strptime(tcmb_data.pop(cls.tcmb_date_key), cls.tcmb_date_format).date()
        tcmb_data.pop(cls.strip_key)
        for key in tcmb_data.keys():
            for_selling = 0
            for_buying = 0
            key_list = str(key).split("_")
            from_currency = key_list[2]
            if key_list[3] == cls.selling_code:
                for_selling = 1
            elif key_list[3] == cls.buying_code:
                for_buying = 1
            # check if record exists by filters
            if not frappe.db.exists({
                "doctype": cls.doctype,
                "date": exchange_rate_date,
                "from_currency": from_currency,
                "to_currency": cls.to_currency,
                "for_buying": for_buying,
                "for_selling": for_selling
            }):
                newdoc = frappe.new_doc(cls.doctype)
                newdoc.date = exchange_rate_date
                newdoc.from_currency = from_currency
                newdoc.to_currency = cls.to_currency
                newdoc.for_buying = for_buying
                newdoc.for_selling = for_selling
                newdoc.exchange_rate = flt(tcmb_data.get(key))
                newdoc.insert()
            else:
                frdoc = frappe.get_doc(doctype=cls.doctype, filters={
                    "date": exchange_rate_date,
                    "from_currency": from_currency,
                    "to_currency": cls.to_currency,
                    "for_buying": for_buying,
                    "for_selling": for_selling
                })
                frdoc.exchange_rate = flt(tcmb_data.get(key))
                frdoc.save()
