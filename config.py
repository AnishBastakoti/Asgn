import hashlib

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    APP_NAME: str = "SkillPulse"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    SECRET_KEY: str
    API_KEY: str
    FINGERPRINT_SALT: str
    API_KEY_BASE_PREFIX: str = "AB"
    API_KEY_ENVIRONMENT: str = "liv"

   # Loaded from .env
    DB_HOST: str
    DB_PORT: int
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str

    API_PREFIX: str = "/api"
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:5500",
    ]

    CORS_ALLOW_METHODS: list[str] = [
        "GET",
        "POST",
    ]

    CORS_ALLOW_HEADERS: list[str] = [
        "Content-Type",
        "Authorization",
    ]

    EMBEDDING_DIM: int = 1536
    UMAP_N_NEIGHBORS: int = 15
    UMAP_MIN_DIST: float = 0.1
    SIMILARITY_THRESHOLD: float = 0.75
    TOP_N_SKILLS: int = 20

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    @property
    def KEY_PREFIX(self) -> str:
        """
        Generates the prefix dynamically based on environment and salt.
        """
        # Reproducing fingerprint logic centrally
        _AUTHOR_KEY = "MSIT402 CIM-10236"
        combined_key = f"{_AUTHOR_KEY}{self.FINGERPRINT_SALT}"
        _SIGNATURE = hashlib.sha256(combined_key.encode()).hexdigest()[:8].upper()
        _ENV = "liv" if not self.DEBUG else "tst"
        
        return f"{self.API_KEY_BASE_PREFIX}{_SIGNATURE}{_ENV}"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()