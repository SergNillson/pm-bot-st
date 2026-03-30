"""Private key encryption and management using PBKDF2 + Fernet."""
import base64
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class KeyManager:
    """Manages encrypted storage of Ethereum private keys."""

    def __init__(self, data_dir: str = "credentials"):
        self.data_dir = data_dir

    def encrypt_key(self, private_key: str, password: str) -> dict:
        """Encrypt a private key using PBKDF2 + Fernet.

        Returns a dict with 'encrypted_key' and 'salt' (both base64-encoded strings).
        """
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100_000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        fernet = Fernet(key)
        encrypted = fernet.encrypt(private_key.encode())
        return {
            "encrypted_key": base64.b64encode(encrypted).decode(),
            "salt": base64.b64encode(salt).decode(),
        }

    def decrypt_key(self, encrypted_data: dict, password: str) -> str:
        """Decrypt a private key from an encrypted_data dict."""
        salt = base64.b64decode(encrypted_data["salt"])
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100_000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        fernet = Fernet(key)
        encrypted = base64.b64decode(encrypted_data["encrypted_key"])
        return fernet.decrypt(encrypted).decode()

    def save_key(self, private_key: str, password: str, filename: str = "key.json") -> None:
        """Encrypt and save a private key to data_dir/filename as JSON."""
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        encrypted_data = self.encrypt_key(private_key, password)
        path = Path(self.data_dir) / filename
        with open(path, "w") as f:
            json.dump(encrypted_data, f)

    def load_key(self, password: str, filename: str = "key.json") -> str:
        """Load and decrypt a private key from data_dir/filename."""
        path = Path(self.data_dir) / filename
        with open(path, "r") as f:
            encrypted_data = json.load(f)
        return self.decrypt_key(encrypted_data, password)
