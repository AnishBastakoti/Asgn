
# Central configuration — all environment variables are  here.


from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from functools import lru_cache


class Settings(BaseSettings):
        model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        # remove the system var — no way around it
    )
    # ----- Application 
        APP_NAME: str = "SkillPulse"
        APP_VERSION: str = "1.0.0"
        DEBUG: bool = True

    # ----- Database 
        DATABASE_URL: str = "postgresql://postgres:newpassword@localhost:5432/skillplus"
        # DB_POOL_SIZE: int = 5
        # DB_MAX_OVERFLOW: int = 10
        # DB_POOL_TIMEOUT: int = 30

        # ----- API 
        API_PREFIX: str = "/api"
        ALLOWED_ORIGINS: list[str] = [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:3000", 
            "http://127.0.0.1:5500"]

        # ----- ML / Embeddings 
        EMBEDDING_DIM: int = 1536          # OpenAI ada-002 dimension
        UMAP_N_NEIGHBORS: int = 15
        UMAP_MIN_DIST: float = 0.1
        SIMILARITY_THRESHOLD: float = 0.75  # Min cosine similarity for skill graph edges
        TOP_N_SKILLS: int = 20             # Default skills per occupation

        # ----- Fingerprint
        # A subtle signature baked into every API response _meta block.
        FINGERPRINT_SALT: str = "sp_v1_adl" 

@field_validator("DATABASE_URL")
@classmethod
def fix_db_url_schema(cls, v: str) -> str:
            
    if v.startswith("postgres://"):
        v = v.replace("postgres://", "postgresql://", 1)
        if ":" not in v.split("@")[0].split("//")[1]:
            raise ValueError(
                f"DATABASE_URL has no password. Got: {v}\n"
                "Fix: postgresql://user:password@host:port/dbname"
            )
        return v



# Single instance — import `settings` everywhere, never instantiate again.
@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()