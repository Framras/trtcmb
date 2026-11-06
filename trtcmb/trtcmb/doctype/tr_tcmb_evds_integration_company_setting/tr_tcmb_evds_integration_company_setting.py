# Copyright (c) 2019, Framras AS-Izmir and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from trtcmb.recording import FIRST_WORKING_DAY, IMMEDIATE_DAY, RECORDING_RULES
from trtcmb.TCMBCurrencyExchange import MAX_BATCH_DAYS, RateOptions, rate_option_error


class TRTCMBEVDSIntegrationCompanySetting(Document):
    def validate(self) -> None:
        if cint(self.batch_days) < 1 or cint(self.batch_days) > MAX_BATCH_DAYS:
            frappe.throw(_("Batch Size must be between 1 and {0} days.").format(MAX_BATCH_DAYS))

        if not self.rate_recording_rule:
            self.rate_recording_rule = FIRST_WORKING_DAY
        elif self.rate_recording_rule not in RECORDING_RULES:
            frappe.throw(
                _("Rate Recording Rule must be {0} or {1}.").format(FIRST_WORKING_DAY, IMMEDIATE_DAY)
            )

        message = rate_option_error(
            RateOptions(
                cint(self.fetch_buying_rate),
                cint(self.buying_rate_for_buying),
                cint(self.buying_rate_for_selling),
                cint(self.fetch_selling_rate),
                cint(self.selling_rate_for_buying),
                cint(self.selling_rate_for_selling),
            )
        )
        if message:
            frappe.throw(_(message))
