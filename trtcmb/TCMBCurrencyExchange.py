import frappe
import datetime

from frappe.utils.data import flt


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
    def commit_single_currency_exchange_rate(cls, tcmb_data: dict):
        data_dict = dict(tcmb_data.get("items")[0])
        exchange_rate_date = datetime.datetime.strptime(data_dict.pop(cls.tcmb_date_key), cls.tcmb_date_format).date()
        data_dict.pop(cls.tcmb_strip_key)
        for key in data_dict.keys():
            for_selling = 0
            for_buying = 0
            key_list = str(key).split(cls.response_separator)
            from_currency = key_list[2]
            if key_list[3] == cls.selling_code:
                for_selling = 1
            elif key_list[3] == cls.buying_code:
                for_buying = 1
            # check if record exists by filters
            if frappe.db.exists({
                "doctype": cls.doctype,
                "date": exchange_rate_date,
                "from_currency": from_currency,
                "to_currency": cls.to_currency,
                "for_buying": for_buying,
                "for_selling": for_selling
            }):
                frdoc_list = frappe.db.get_list(doctype=cls.doctype, filters={
                    "date": exchange_rate_date,
                    "from_currency": from_currency,
                    "to_currency": cls.to_currency,
                    "for_buying": for_buying,
                    "for_selling": for_selling
                })
                frdoc = frappe.get_doc(cls.doctype, frdoc_list[0].get("name"))
                if frdoc.exchange_rate != flt(data_dict.get(key)):
                    frdoc.exchange_rate = flt(data_dict.get(key))
                    return frappe.enqueue(frdoc.save, queue="short", timeout=None, event=None,
                                          now=True, job_name=None)
            else:
                newdoc = frappe.new_doc(cls.doctype)
                newdoc.date = exchange_rate_date
                newdoc.from_currency = from_currency
                newdoc.to_currency = cls.to_currency
                newdoc.for_buying = for_buying
                newdoc.for_selling = for_selling
                newdoc.exchange_rate = flt(data_dict.get(key))
                return frappe.enqueue(newdoc.insert, queue="short", timeout=None, event=None,
                                      now=True, job_name=None)
