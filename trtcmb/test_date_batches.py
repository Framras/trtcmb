from datetime import date

from frappe.tests import UnitTestCase

from trtcmb.TCMBConnection import iter_date_batches


class TestTCMBDateBatches(UnitTestCase):
    def test_five_day_batches_cover_the_full_requested_range(self):
        batches = iter_date_batches(date(2026, 1, 1), date(2026, 1, 12), batch_days=5)

        self.assertEqual(
            batches,
            [
                (date(2026, 1, 1), date(2026, 1, 5)),
                (date(2026, 1, 6), date(2026, 1, 10)),
                (date(2026, 1, 11), date(2026, 1, 12)),
            ],
        )

    def test_single_day_range_is_one_batch(self):
        batches = iter_date_batches(date(2026, 11, 3), date(2026, 11, 3), batch_days=5)
        self.assertEqual(batches, [(date(2026, 11, 3), date(2026, 11, 3))])
