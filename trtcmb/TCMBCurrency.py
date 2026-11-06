import time

import frappe
import requests
from frappe import _

from trtcmb.TCMBCurrencyExchange import TCMBCurrencyExchange

RETRYABLE_STATUS = {429, 502, 503, 504}


class TCMBCurrency:
    doctype = "Currency"
    company_doctype = "Company"
    response_type = "json"
    serielist_path = "/serieList"
    code_prefix = "/code="
    type_prefix = "&type="
    datagroup_code = "bie_dkdovizgn"
    company_setting_doctype = "TR TCMB EVDS Integration Company Setting"
    integration_setting_doctype = "TR TCMB EVDS Integration Setting"

    @classmethod
    def get_service_path(cls) -> str:
        service_path = frappe.db.get_single_value(cls.integration_setting_doctype, "service_path")
        if not service_path:
            frappe.throw(
                _("Set the TCMB EVDS Service Path in {0}.").format(_(cls.integration_setting_doctype))
            )
        return str(service_path).strip().rstrip("/")

    @classmethod
    def get_list_of_enabled_currencies(cls, company: str | None = None) -> list[dict]:
        currency_list = frappe.get_all(
            cls.doctype,
            filters={"enabled": 1, "name": ["not in", ["TRY", "XAU"]]},
            fields=["name"],
        )
        if not currency_list:
            return []

        company = company or frappe.defaults.get_user_default(cls.company_doctype)
        key = frappe.db.get_value(cls.company_setting_doctype, company, "key")
        if not key:
            frappe.throw(
                _("Set the TCMB EVDS Integration Key for company {0}.").format(company or _("(none)"))
            )

        url = (
            cls.get_service_path()
            + cls.serielist_path
            + cls.code_prefix
            + cls.datagroup_code
            + cls.type_prefix
            + cls.response_type
        )
        tcmb_data_series = cls.request_json(url, str(key))
        series_items = cls.as_item_list(tcmb_data_series)

        enabled_names = {c.get("name") for c in currency_list}
        series_by_currency: dict[str, dict] = {}
        for tcmb_data_item in series_items:
            serie_code = str(
                tcmb_data_item.get("Serie_Code")
                or tcmb_data_item.get("SERIE_CODE")
                or tcmb_data_item.get("serieCode")
                or ""
            )
            tcmb_currency_data = serie_code.split(".")
            # EVDS2: TP.DK.USD.A  |  EVDS3: TP.DK.USD.A.YTL
            if len(tcmb_currency_data) < 4:
                continue
            currency_code = tcmb_currency_data[2]
            rate_type = tcmb_currency_data[3]
            if currency_code not in enabled_names or rate_type not in (
                TCMBCurrencyExchange.buying_code,
                TCMBCurrencyExchange.selling_code,
            ):
                continue
            currency_row = series_by_currency.setdefault(
                currency_code, {"name": currency_code, "buying_series": None, "selling_series": None}
            )
            if rate_type == TCMBCurrencyExchange.buying_code:
                currency_row["buying_series"] = serie_code
            else:
                currency_row["selling_series"] = serie_code

        return [
            row
            for row in series_by_currency.values()
            if row.get("buying_series") or row.get("selling_series")
        ]

    @classmethod
    def request_json(cls, url: str, key: str, retries: int = 4):
        headers = {
            "key": key,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        last_error: str | None = None

        for attempt in range(retries):
            try:
                response = requests.get(url, headers=headers, timeout=60)
            except requests.RequestException as exc:
                last_error = str(exc)
                cls.pause(2**attempt)
                continue

            if response.status_code in RETRYABLE_STATUS:
                last_error = _("HTTP {0}").format(response.status_code)
                cls.pause(2**attempt)
                continue

            if response.status_code != 200:
                frappe.throw(
                    _("TCMB API Error {0}: {1}").format(response.status_code, response.text[:250])
                )

            try:
                return response.json()
            except ValueError:
                frappe.throw(_("TCMB API returned a non-JSON response: {0}").format(response.text[:250]))

        frappe.throw(_("TCMB API request failed after retries: {0}").format(last_error or _("unknown error")))

    @staticmethod
    def as_item_list(payload) -> list:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            items = payload.get("items") or payload.get("data") or payload.get("series") or []
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        frappe.throw(_("Unexpected JSON response from TCMB: {0}").format(str(payload)[:250]))

    @staticmethod
    def pause(seconds: float) -> None:
        if seconds <= 0 or getattr(frappe.flags, "in_test", False):
            return
        time.sleep(seconds)
