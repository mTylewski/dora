"""Application-level encryption of case data (Fernet: AES-128-CBC + HMAC).

Applies on top of the encrypted volume: the database holds only ciphertext
for anonymization mappings and analysis results.
Generate a key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet


class Box:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    def seal(self, data: Any) -> bytes:
        return self._fernet.encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def open(self, token: bytes | None) -> Any:
        if token is None:
            return None
        return json.loads(self._fernet.decrypt(token).decode("utf-8"))
