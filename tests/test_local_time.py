import unittest
from app.services.local_time import greeting_for_hour


class LocalGreetingTests(unittest.TestCase):
    def test_morning(self):
        self.assertEqual(greeting_for_hour(5), "Bom dia")
        self.assertEqual(greeting_for_hour(11), "Bom dia")

    def test_afternoon(self):
        self.assertEqual(greeting_for_hour(12), "Boa tarde")
        self.assertEqual(greeting_for_hour(17), "Boa tarde")

    def test_night(self):
        self.assertEqual(greeting_for_hour(0), "Boa noite")
        self.assertEqual(greeting_for_hour(4), "Boa noite")
        self.assertEqual(greeting_for_hour(18), "Boa noite")
        self.assertEqual(greeting_for_hour(23), "Boa noite")


if __name__ == "__main__":
    unittest.main()
