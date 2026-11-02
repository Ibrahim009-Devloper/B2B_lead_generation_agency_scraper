import pytest
from pydantic import BaseModel
from config.settings import settings
from core.llm_router import llm_router, TaskType, KeyHealth, ProviderPool

class AgencyClassificationModel(BaseModel):
    is_agency: bool
    agency_type: str
    confidence: float

def test_key_counts():
    groq_keys = settings.get_groq_keys()
    gemini_keys = settings.get_gemini_keys()
    assert len(groq_keys) == 5, f"Expected 5 Groq keys, got {len(groq_keys)}"
    assert len(gemini_keys) == 5, f"Expected 5 Gemini keys, got {len(gemini_keys)}"

def test_key_health_cooldown():
    health = KeyHealth("test_key", 0)
    assert health.is_available() is True
    
    # Simulate a rate-limit failure
    health.mark_failure(is_rate_limit=True, cooldown_seconds=10)
    assert health.is_available() is False
    assert health.consecutive_errors == 1

def test_round_robin_selection():
    pool = ProviderPool("test_pool", ["key1", "key2", "key3"])
    k1 = pool.get_available_key()
    k2 = pool.get_available_key()
    k3 = pool.get_available_key()
    k4 = pool.get_available_key()
    
    assert k1.key == "key1"
    assert k2.key == "key2"
    assert k3.key == "key3"
    assert k4.key == "key1"

def test_live_groq_fast_classification():
    prompt = "We are an outbound cold email agency helping SaaS companies book demos. Are we an agency? Classify us."
    res = llm_router.route(
        task=TaskType.FAST_CLASSIFICATION,
        prompt=prompt,
        schema=AgencyClassificationModel
    )
    assert res["provider"] in ("groq", "gemini")
    data = res["data"]
    assert isinstance(data, AgencyClassificationModel)
    assert data.is_agency is True
    print("\n[Groq Fast Classification Test Output]:", data)

def test_live_gemini_structured_parsing():
    prompt = "Our agency 'Apex Scale' offers Local SEO & GBP ranking audits for cosmetic dentists in Miami."
    res = llm_router.route(
        task=TaskType.WEBSITE_PARSING,
        prompt=prompt,
        schema=AgencyClassificationModel
    )
    assert res["provider"] in ("gemini", "groq")
    data = res["data"]
    assert isinstance(data, AgencyClassificationModel)
    assert data.is_agency is True
    print("\n[Gemini Structured Parsing Test Output]:", data)
