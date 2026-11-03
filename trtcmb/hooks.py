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

scheduler_events = {
    "cron": {
        "58 00 * * *": [
            "trtcmb.tasks.every_day_at_00_58"
        ]
    }
}
