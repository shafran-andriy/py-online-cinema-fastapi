from abc import ABC, abstractmethod


class JWTAuthManagerInterface(ABC):

    @abstractmethod
    def create_access_token(self, subject: str, expires_delta: int) -> str:
        ...

    @abstractmethod
    def create_refresh_token(self, subject: str, expires_delta: int) -> str:
        ...

    @abstractmethod
    def decode_access_token(self, token: str) -> dict:
        ...
