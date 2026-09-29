"""Password hashing compatibility and upgrade tests."""

import hashlib
import os
import unittest

import main


def legacy_pbkdf2_hash(password):
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
    ).hex()
    return f"{salt}:{digest}"


class PasswordHashingTests(unittest.TestCase):
    def test_new_passwords_use_argon2id(self):
        stored = main.hash_password("A long and unique test passphrase")

        self.assertTrue(stored.startswith("$argon2id$"))
        self.assertTrue(main.verify_password("A long and unique test passphrase", stored))
        self.assertFalse(main.verify_password("incorrect password", stored))

    def test_legacy_pbkdf2_passwords_remain_valid(self):
        stored = legacy_pbkdf2_hash("Existing account passphrase")

        self.assertTrue(main.verify_password("Existing account passphrase", stored))
        self.assertFalse(main.verify_password("incorrect password", stored))
        self.assertTrue(main.password_hash_needs_upgrade(stored))

    def test_current_argon2id_hash_does_not_need_upgrade(self):
        stored = main.hash_password("Another long and unique passphrase")

        self.assertFalse(main.password_hash_needs_upgrade(stored))

    def test_malformed_hash_fails_closed(self):
        self.assertFalse(main.verify_password("anything", "$argon2id$invalid"))
        self.assertTrue(main.password_hash_needs_upgrade("not-a-valid-hash"))


if __name__ == "__main__":
    unittest.main()
