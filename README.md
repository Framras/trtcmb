## Trtcmb

TR Turkish Central Bank EVDS web services integration of economic data for ErpNext

### Description

ERPNext custom app for importing "Exchange, rates, Daily, (Converted, to, TRY)" series for enabled currencies in an ERPNext instance

An ERPNext system wide URL of TCMB service should be defined by System Administrator. (DocType=TR TCMB EVDS Integration Setting)

Each ERPNext Company should define their integration code, integration start date save these settings and initiate integration. (DocType=TR TCMB EVDS Integration Company Setting)

Checks currencies enabled in your ERPNext instance against the currencies announced by TCMB. The currency exchange rates are legally accepted rates.

Checks Currency Exchange rates in ERPNext and skips updates. Inserts new buying and selling Currency Exchange rates for enabled currencies for dates starting from integration start date. Rates are received from TCMB.

### Known Issues

* for updates of more than 30 days' data, a database lock timeout message is received. So, it is advised to initiate the data backwards adding another month on each step.
* you need first to delete the Currency Exchange entries in your ERPNext system if you want to refresh them from TCMB.

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
