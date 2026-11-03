// Copyright (c) 2019, Framras AS-Izmir and contributors
// For license information, please see license.txt

frappe.ui.form.on("TR TCMB EVDS Integration Company Setting", {
	initiate_integration: function (frm) {
		if (frm.doc.enable != 0) {
			frappe.call({
				method: "trtcmb.api.initiate_currency_exchange_rates",
				args: {
					company: frm.doc.company_name,
				},
				freeze: true,
				freeze_message: __("Queueing TCMB exchange rate import..."),
				callback: function () {
					frappe.show_alert({
						message: __("TCMB import started in 5-day batches in the background."),
						indicator: "green",
					});
				},
			});
		}
	},
});
