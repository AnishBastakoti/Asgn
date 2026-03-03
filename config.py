from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
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

    DATABASE_URL: str = "postgresql://postgres:newpassword@localhost:5432/skillplus"

    API_PREFIX: str = "/api"
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:5500",
    ]

    EMBEDDING_DIM: int = 1536
    UMAP_N_NEIGHBORS: int = 15
    UMAP_MIN_DIST: float = 0.1
    SIMILARITY_THRESHOLD: float = 0.75
    TOP_N_SKILLS: int = 20
    FINGERPRINT_SALT: str = "sp_v1_adl"

    @field_validator("DATABASE_URL")
    @classmethod
    def fix_db_url_schema(cls, v: str) -> str:
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql://", 1)
        return v


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()