from __future__ import unicode_literals

from trtcmb import api as api


def every_day_at_00_58():
    api.initiate_currency_exchange_rates()
