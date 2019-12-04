## Trtcmb

TR Turkish Central Bank EVDS web services integration of economic data for ErpNext

### Description

ERPNext custom app for importing "Exchange, rates, Daily, (Converted, to, TRY)" series for enabled currencies in an ERPNext instance

An ERPNext system wide URL of TCMB service should be defined by System Administrator. (DocType=TR TCMB EVDS Integration Setting)

Each ERPNext Company should define their integration code, integration start date save these settings and initiate integration. (DocType=TR TCMB EVDS Integration Company Setting)

Checks currencies enabled in your ERPNext instance against the currencies announced by TCMB. The currency exchange rates are legally accepted rates.

Checks existing Currency Exchange rates in ERPNext against TCMB rates and updates with rates are received from TCMB.

Can handle for updates beyond 30 days' data via background jobs

### Known Issues

* please report any issues you encounter

### Installation

Go to your folder containing bench and run:

bench get-app https://github.com/Framras/trtcmb.git

At the same prompt run:

bench --site [your_site_name] install-app trtcmb

### Update

Go to the app folder and run:

git pull https://github.com/Framras/trtcmb.git

Go to your folder containing bench and run:

bench build

bench migrate

#### License

MIT
