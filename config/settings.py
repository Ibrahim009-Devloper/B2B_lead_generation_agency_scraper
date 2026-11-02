import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Settings(BaseModel):
    # App config
    PROJECT_NAME: str = "Autonomous Multi-Agent Lead Gen System"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/lead_gen.db")
    
    # Groq Multi-Key Pool (5 slots)
    GROQ_API_KEY_1: Optional[str] = os.getenv("GROQ_API_KEY_1")
    GROQ_API_KEY_2: Optional[str] = os.getenv("GROQ_API_KEY_2")
    GROQ_API_KEY_3: Optional[str] = os.getenv("GROQ_API_KEY_3")
    GROQ_API_KEY_4: Optional[str] = os.getenv("GROQ_API_KEY_4")
    GROQ_API_KEY_5: Optional[str] = os.getenv("GROQ_API_KEY_5")
    
    # Gemini Multi-Key Pool (5 slots)
    GEMINI_API_KEY_1: Optional[str] = os.getenv("GEMINI_API_KEY_1")
    GEMINI_API_KEY_2: Optional[str] = os.getenv("GEMINI_API_KEY_2")
    GEMINI_API_KEY_3: Optional[str] = os.getenv("GEMINI_API_KEY_3")
    GEMINI_API_KEY_4: Optional[str] = os.getenv("GEMINI_API_KEY_4")
    GEMINI_API_KEY_5: Optional[str] = os.getenv("GEMINI_API_KEY_5")
    
    # DeepSeek API Key (Optional)
    DEEPSEEK_API_KEY: Optional[str] = os.getenv("DEEPSEEK_API_KEY")
    
    # Primary Models
    GROQ_MODEL_FAST: str = "qwen/qwen3.8-27b"
    GROQ_MODEL_LIGHT: str = "qwen/qwen3.8-27b"
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    
    # System Quotas and Rate Limits
    DEFAULT_DAILY_TOKEN_LIMIT: int = int(os.getenv("DEFAULT_DAILY_TOKEN_LIMIT", "500000"))
    COOLDOWN_PERIOD_SECONDS: int = 60
    MAX_RETRIES_PER_PROVIDER: int = 3
    
    # 100-Point Scoring Model Max Weights
    WEIGHT_ICP_FIT: int = 25
    WEIGHT_DATA_NEED: int = 25
    WEIGHT_NICHE_SPECIFICITY: int = 15
    WEIGHT_CONTACT_RELIABILITY: int = 15
    WEIGHT_DECISION_MAKER: int = 10
    WEIGHT_FRESHNESS: int = 10
    
    # Score Thresholds
    THRESHOLD_HIGH_POTENTIAL: int = 80
    THRESHOLD_QUALIFIED: int = 65
    THRESHOLD_NEEDS_REVIEW: int = 50
    CONFIDENCE_HIGH_THRESHOLD: float = 0.80
    CONFIDENCE_QUALIFIED_THRESHOLD: float = 0.70

    def get_groq_keys(self) -> List[str]:
        keys = []
        for k in [self.GROQ_API_KEY_1, self.GROQ_API_KEY_2, self.GROQ_API_KEY_3, self.GROQ_API_KEY_4, self.GROQ_API_KEY_5]:
            if k and k.strip() and not k.startswith("your_"):
                keys.append(k.strip())
        legacy = os.getenv("GROQ_API_KEY")
        if legacy and legacy not in keys:
            keys.append(legacy.strip())
        return keys

    def get_gemini_keys(self) -> List[str]:
        keys = []
        for k in [self.GEMINI_API_KEY_1, self.GEMINI_API_KEY_2, self.GEMINI_API_KEY_3, self.GEMINI_API_KEY_4, self.GEMINI_API_KEY_5]:
            if k and k.strip() and not k.startswith("your_"):
                keys.append(k.strip())
        legacy = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if legacy and legacy not in keys:
            keys.append(legacy.strip())
        return keys

settings = Settings()
