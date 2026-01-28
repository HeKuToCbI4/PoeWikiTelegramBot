from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # PoE Wiki API settings
    poe_wiki_api_url: str = "https://www.poewiki.net/w/api.php"
    
    # Telegram Bot settings
    telegram_bot_token: Optional[str] = None
    
    # Logging settings
    log_level: str = "INFO"
    
    # Configuration for loading from environment variables or .env file
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
