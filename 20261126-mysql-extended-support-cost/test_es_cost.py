import json, os, tempfile, unittest
from datetime import date
import es_cost

CAL = es_cost.load("calendar.json")


class Arithmetic(unittest.TestCase):
    def test_blog_example_years_1_2(self):
        # 8 vCPU x 3 instances x 0.100 USD x 8,760 h = 21,024 USD, RDS for MySQL 8.0, a year inside years 1-2
        h1, h3, cost, _ = es_cost.cost_window(CAL["mysql"]["8.0"], 24, date(2026, 8, 1), date(2027, 8, 1), 0.100, 0.200)
        self.assertEqual((h1, h3), (8760, 0))
        self.assertAlmostEqual(cost, 21024.0)

    def test_blog_example_year_3(self):
        h1, h3, cost, _ = es_cost.cost_window(CAL["mysql"]["8.0"], 24, date(2028, 8, 1), date(2029, 8, 1), 0.100, 0.200)
        self.assertEqual((h1, h3), (0, 8760))
        self.assertAlmostEqual(cost, 42048.0)

    def test_split_at_year_3(self):
        # Aurora v2: year 3 rate from 1 Dec 2026; one day at each rate
        h1, h3, cost, _ = es_cost.cost_window(CAL["aurora-mysql"]["5.7"], 1, date(2026, 11, 30), date(2026, 12, 2), 0.1, 0.2)
        self.assertEqual((h1, h3), (24, 24))
        self.assertAlmostEqual(cost, 24 * 0.1 + 24 * 0.2)

    def test_standard_support_costs_nothing(self):
        _, _, cost, _ = es_cost.cost_window(CAL["aurora-mysql"]["8.0"], 8, date(2026, 11, 26), date(2027, 11, 26), 0.1, 0.2)
        self.assertEqual(cost, 0.0)

    def test_stops_at_end_of_extended_support(self):
        h1, h3, _, note = es_cost.cost_window(CAL["aurora-mysql"]["5.7"], 1, date(2029, 6, 30), date(2029, 7, 10), 0.1, 0.2)
        self.assertEqual((h1, h3), (0, 24))
        self.assertIn("2029-06-30", note)


if __name__ == "__main__":
    unittest.main()
