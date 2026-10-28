from cryptography.fernet import Fernet, InvalidToken

from pengucoach.common.config import settings


class SecretBox:
    def __init__(self) -> None:
        if not settings.encryption_key:
            raise RuntimeError("PENGUCOACH_ENCRYPTION_KEY is required for secret storage")
        self._fernet = Fernet(settings.encryption_key.encode())

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise RuntimeError("Unable to decrypt stored secret") from exc
