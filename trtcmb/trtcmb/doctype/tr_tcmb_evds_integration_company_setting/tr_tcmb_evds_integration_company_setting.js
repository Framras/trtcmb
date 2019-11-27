// Copyright (c) 2019, Framras AS-Izmir and contributors
// For license information, please see license.txt

frappe.ui.form.on('TR TCMB EVDS Integration Company Setting', {
	// refresh: function(frm) {

	// }
	initiate_integration: function(frm){
	    if((frm.doc.enable!=0)){
	        frappe.call({
	            method: "trtcmb.api.initiate_currency_exchange_rates",
	            args:{
	            },
	            callback: function(r){
                    frm.set_value("last_updated", r.message);
                    frm.save();
	            }
	        })
	    }
	}
});
