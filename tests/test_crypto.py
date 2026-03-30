"""Tests for KeyManager from src/crypto.py."""
import pytest
from src.crypto import KeyManager

TEST_KEY = "0x" + "a" * 64
TEST_PASSWORD = "test_password_123"


class TestKeyManager:
    def test_encrypt_decrypt_roundtrip(self):
        km = KeyManager()
        encrypted = km.encrypt_key(TEST_KEY, TEST_PASSWORD)

        assert "encrypted_key" in encrypted
        assert "salt" in encrypted

        decrypted = km.decrypt_key(encrypted, TEST_PASSWORD)
        assert decrypted == TEST_KEY

    def test_wrong_password_fails(self):
        km = KeyManager()
        encrypted = km.encrypt_key(TEST_KEY, TEST_PASSWORD)

        with pytest.raises(Exception):
            km.decrypt_key(encrypted, "wrong_password")

    def test_save_load_roundtrip(self, tmp_path):
        km = KeyManager(data_dir=str(tmp_path))
        km.save_key(TEST_KEY, TEST_PASSWORD)

        loaded = km.load_key(TEST_PASSWORD)
        assert loaded == TEST_KEY

    def test_encrypted_data_is_different(self):
        km = KeyManager()
        enc1 = km.encrypt_key(TEST_KEY, TEST_PASSWORD)
        enc2 = km.encrypt_key(TEST_KEY, TEST_PASSWORD)

        # Different salt each time → different ciphertext
        assert enc1["salt"] != enc2["salt"]
        assert enc1["encrypted_key"] != enc2["encrypted_key"]

    def test_encrypted_key_not_plaintext(self):
        km = KeyManager()
        encrypted = km.encrypt_key(TEST_KEY, TEST_PASSWORD)
        assert TEST_KEY not in encrypted["encrypted_key"]

    def test_save_creates_file(self, tmp_path):
        km = KeyManager(data_dir=str(tmp_path))
        km.save_key(TEST_KEY, TEST_PASSWORD)
        assert (tmp_path / "key.json").exists()

    def test_save_load_custom_filename(self, tmp_path):
        km = KeyManager(data_dir=str(tmp_path))
        km.save_key(TEST_KEY, TEST_PASSWORD, filename="custom.json")
        loaded = km.load_key(TEST_PASSWORD, filename="custom.json")
        assert loaded == TEST_KEY
