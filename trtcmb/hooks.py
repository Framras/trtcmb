from . import __version__ as app_version

app_name = "trtcmb"
app_title = "Trtcmb"
app_publisher = "Framras AS-Izmir"
app_description = "TR Turkish Central Bank EVDS 3 web services integration of economic data for ErpNext"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "bilgi@framras.com.tr"
app_license = "MIT"
required_apps = ["erpnext"]

after_migrate = ["trtcmb.patches.v16_0.retire_journal_entry_extensions.clear_meta_cache"]

scheduler_events = {
    "cron": {
        "*/15 * * * *": [
            "trtcmb.tasks.import_due_companies"
        ]
    }
}
