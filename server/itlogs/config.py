from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"  # server/.env, whatever the cwd


class Settings(BaseSettings):
    """Every knob comes from the environment. Secrets never live in the repo."""

    model_config = SettingsConfigDict(env_prefix="ITLOGS_", env_file=ENV_FILE, extra="ignore")

    provider: str = "fake"  # fake | meta
    meta_api_key: str = Field(
        default="", validation_alias=AliasChoices("ITLOGS_META_API_KEY", "MODEL_API_KEY")
    )  # MODEL_API_KEY is the name Meta's docs use; it lives in ~/.secure_env_vars
    meta_api_base: str = "https://api.meta.ai/v1"
    # the reader (food + display): meta (Muse Spark) or local (Muse Glimmer on llama-server)
    vision: str = "meta"
    vision_model: str = "muse-spark-1.3"
    bowl: bool = True  # ITLOGS_BOWL=0: bowls take the bare-food path (#22)
    # the reply parser: meta (Muse Spark), baseten (Muse Spark Open), local (llama-server)
    llm: str = "meta"
    llm_local_base: str = "http://127.0.0.1:8080/v1"
    llm_local_model: str = "muse-glimmer"
    llm_local_key: str = ""
    baseten_base: str = "https://inference.baseten.co/v1"
    baseten_model: str = "meta-models/muse-spark-open"
    baseten_api_key: str = Field(
        default="", validation_alias=AliasChoices("ITLOGS_BASETEN_API_KEY", "BASETEN_API_KEY")
    )
    usual_foods: str = ""  # comma-separated; the reader checks these first
    second_read_after_ms: int = 1500
    grams_tolerance_g: float = 1.0
    record_dir: str = ""  # set to keep photos and entries for the eval sets
    posthog_token: str = ""  # the PostHog project token (public, write-only); empty = telemetry off
    posthog_host: str = "https://us.i.posthog.com"

    @property
    def usual_food_list(self) -> list[str]:
        return [f.strip() for f in self.usual_foods.split(",") if f.strip()]


settings = Settings()
