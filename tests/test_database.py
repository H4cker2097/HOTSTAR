import os
import tempfile
import unittest

# Set isolated SQLite file before importing database module.
_fd, _path = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["SQLITE_PATH"] = _path

import database


class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()

    def test_create_and_fetch_order(self):
        order_id = database.create_order(12345, "+919876543210")
        order = database.get_order(order_id)
        self.assertEqual(order["telegram_user_id"], 12345)
        self.assertEqual(order["status"], "CREATED")

    def test_status_validation(self):
        order_id = database.create_order(12345, "+919876543210")
        with self.assertRaises(ValueError):
            database.update_order_status(order_id, "MAGIC_SUCCESS")


if __name__ == "__main__":
    unittest.main()
