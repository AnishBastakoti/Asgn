
# Central configuration — all environment variables are  here.


from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ----- Application 
    APP_NAME: str = "SkillPulse"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # ----- Database 
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5433/skillplus"
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
    # This proves the output came from YOUR system.
    FINGERPRINT_SALT: str = "sp_v1_adl"  # Change this to something personal

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Single instance — import `settings` everywhere, never instantiate again.
@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()