import time
import json
import logging
import re
from enum import Enum
from typing import Dict, List, Optional, Any, Type
from pydantic import BaseModel
import groq
from google import genai
from config.settings import settings
from core.schemas import LLMUsageMetric

logger = logging.getLogger("LLMRouter")
logger.setLevel(logging.INFO)

class TaskType(str, Enum):
    FAST_CLASSIFICATION = "fast_classification"
    WEBSITE_PARSING = "website_parsing"
    HTML_EXTRACTION = "html_extraction"
    OUTREACH_IDEATION = "outreach_ideation"
    GENERAL = "general"

class KeyHealth:
    def __init__(self, key: str, index: int):
        self.key = key
        self.index = index
        self.cooldown_until: float = 0.0
        self.consecutive_errors: int = 0
        self.total_calls: int = 0
        self.total_errors: int = 0

    def is_available(self) -> bool:
        return time.time() >= self.cooldown_until

    def mark_success(self):
        self.consecutive_errors = 0
        self.total_calls += 1

    def mark_failure(self, is_rate_limit: bool = False, cooldown_seconds: int = 60):
        self.consecutive_errors += 1
        self.total_errors += 1
        self.total_calls += 1
        wait_time = cooldown_seconds * (2 ** min(self.consecutive_errors - 1, 4)) if is_rate_limit else 15
        self.cooldown_until = time.time() + wait_time
        logger.warning(
            f"Key #{self.index} put on cooldown for {wait_time}s (Error count: {self.consecutive_errors}, RateLimit: {is_rate_limit})"
        )

class ProviderPool:
    def __init__(self, name: str, keys: List[str]):
        self.name = name
        self.keys = [KeyHealth(k, i) for i, k in enumerate(keys)]
        self.current_idx = 0

    @property
    def key_count(self) -> int:
        return len(self.keys)

    def get_next_key(self) -> str:
        key_health = self.get_available_key()
        return key_health.key if key_health else ""

    def get_available_key(self) -> Optional[KeyHealth]:
        if not self.keys:
            return None
        total = len(self.keys)
        for _ in range(total):
            candidate = self.keys[self.current_idx]
            self.current_idx = (self.current_idx + 1) % total
            if candidate.is_available():
                return candidate
        # If all on cooldown, pick the one with earliest cooldown expiry
        earliest = min(self.keys, key=lambda k: k.cooldown_until)
        wait_seconds = max(0.0, earliest.cooldown_until - time.time())
        if wait_seconds < 3.0:
            time.sleep(wait_seconds)
            return earliest
        return None

_ROUTER_INITIALIZED = False

class LLMRouter:
    def __init__(self):
        global _ROUTER_INITIALIZED
        groq_keys = settings.get_groq_keys()
        gemini_keys = settings.get_gemini_keys()
        self.groq_pool = ProviderPool("groq", groq_keys)
        self.gemini_pool = ProviderPool("gemini", gemini_keys)
        self.metrics: List[LLMUsageMetric] = []
        if not _ROUTER_INITIALIZED:
            logger.info(
                f"Initialized LLMRouter with {len(groq_keys)} Groq keys and {len(gemini_keys)} Gemini keys."
            )
            _ROUTER_INITIALIZED = True

    def _call_groq(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        schema: Optional[Type[BaseModel]] = None,
        max_tokens: int = 1500,
        temperature: float = 0.2
    ) -> Dict[str, Any]:
        key_health = self.groq_pool.get_available_key()
        if not key_health:
            raise RuntimeError("All Groq API keys are currently exhausted or on cooldown.")
        
        target_model = model or settings.GROQ_MODEL_FAST
        client = groq.Groq(api_key=key_health.key)
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        start_time = time.time()
        try:
            kwargs = {
                "model": target_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature
            }
            if schema:
                # Ensure the word 'json' and schema structure are present in messages to satisfy Groq API requirements
                schema_keys = list(schema.model_fields.keys())
                json_instruction = (
                    f" You must respond strictly with a valid JSON object adhering to this schema format. "
                    f"Required keys: {schema_keys}."
                )
                if system_prompt:
                    messages[0]["content"] += f"\n{json_instruction}"
                else:
                    messages.insert(0, {"role": "system", "content": f"You are a precise JSON extractor.{json_instruction}"})
                kwargs["response_format"] = {"type": "json_object"}
            
            resp = client.chat.completions.create(**kwargs)
            latency = (time.time() - start_time) * 1000
            content = resp.choices[0].message.content or ""
            key_health.mark_success()

            # Record telemetry
            usage = resp.usage
            prompt_tok = usage.prompt_tokens if usage else 0
            comp_tok = usage.completion_tokens if usage else 0
            self.metrics.append(LLMUsageMetric(
                provider="groq",
                model=target_model,
                key_index=key_health.index,
                prompt_tokens=prompt_tok,
                completion_tokens=comp_tok,
                latency_ms=latency,
                cost_estimate_usd=(prompt_tok * 0.05 + comp_tok * 0.08) / 1_000_000,
                success=True
            ))

            if schema:
                parsed = self._extract_json_to_schema(content, schema)
                return {"data": parsed, "raw": content, "provider": "groq", "model": target_model}
            return {"data": content, "raw": content, "provider": "groq", "model": target_model}

        except Exception as e:
            err_str = str(e).lower()
            is_429 = "429" in err_str or "rate limit" in err_str or "quota" in err_str
            key_health.mark_failure(is_rate_limit=is_429, cooldown_seconds=settings.COOLDOWN_PERIOD_SECONDS)
            self.metrics.append(LLMUsageMetric(
                provider="groq",
                model=target_model,
                key_index=key_health.index,
                latency_ms=(time.time() - start_time) * 1000,
                success=False,
                error_message=str(e)
            ))
            raise e

    def _call_gemini(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.2
    ) -> Dict[str, Any]:
        key_health = self.gemini_pool.get_available_key()
        if not key_health:
            raise RuntimeError("All Gemini API keys are currently exhausted or on cooldown.")
        
        target_model = model or settings.GEMINI_MODEL
        client = genai.Client(api_key=key_health.key)
        
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        start_time = time.time()
        
        config: Dict[str, Any] = {"temperature": temperature}
        if schema:
            config["response_mime_type"] = "application/json"
            config["response_schema"] = schema

        try:
            resp = client.models.generate_content(
                model=target_model,
                contents=full_prompt,
                config=config
            )
            latency = (time.time() - start_time) * 1000
            content = resp.text or ""
            key_health.mark_success()

            # Record telemetry
            meta = getattr(resp, "usage_metadata", None)
            prompt_tok = getattr(meta, "prompt_token_count", 0) if meta else 0
            comp_tok = getattr(meta, "candidates_token_count", 0) if meta else 0
            self.metrics.append(LLMUsageMetric(
                provider="gemini",
                model=target_model,
                key_index=key_health.index,
                prompt_tokens=prompt_tok,
                completion_tokens=comp_tok,
                latency_ms=latency,
                cost_estimate_usd=(prompt_tok * 0.075 + comp_tok * 0.30) / 1_000_000,
                success=True
            ))

            if schema:
                parsed = self._extract_json_to_schema(content, schema)
                return {"data": parsed, "raw": content, "provider": "gemini", "model": target_model}
            return {"data": content, "raw": content, "provider": "gemini", "model": target_model}

        except Exception as e:
            err_str = str(e).lower()
            is_429 = "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str
            key_health.mark_failure(is_rate_limit=is_429, cooldown_seconds=settings.COOLDOWN_PERIOD_SECONDS)
            self.metrics.append(LLMUsageMetric(
                provider="gemini",
                model=target_model,
                key_index=key_health.index,
                latency_ms=(time.time() - start_time) * 1000,
                success=False,
                error_message=str(e)
            ))
            raise e

    def _extract_json_to_schema(self, text: str, schema: Type[BaseModel]) -> BaseModel:
        clean = text.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        
        # Regex search for first { ... }
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if match:
            clean = match.group(0)
            
        data = json.loads(clean)
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            data = data[0]
        return schema.model_validate(data)

    def route(
        self,
        task: TaskType,
        prompt: str,
        system_prompt: Optional[str] = None,
        schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.2
    ) -> Dict[str, Any]:
        """
        Executes with primary provider based on task routing matrix,
        falling back automatically to secondary provider on error.
        """
        if task == TaskType.FAST_CLASSIFICATION:
            primary_fn = self._call_groq
            secondary_fn = self._call_gemini
            primary_name, secondary_name = "Groq", "Gemini"
        elif task in (TaskType.WEBSITE_PARSING, TaskType.HTML_EXTRACTION, TaskType.OUTREACH_IDEATION):
            primary_fn = self._call_gemini
            secondary_fn = self._call_groq
            primary_name, secondary_name = "Gemini", "Groq"
        else:
            primary_fn = self._call_groq
            secondary_fn = self._call_gemini
            primary_name, secondary_name = "Groq", "Gemini"

        try:
            return primary_fn(prompt=prompt, system_prompt=system_prompt, schema=schema, temperature=temperature)
        except Exception as primary_err:
            logger.warning(f"Primary provider {primary_name} failed: {primary_err}. Falling back to {secondary_name}...")
            try:
                return secondary_fn(prompt=prompt, system_prompt=system_prompt, schema=schema, temperature=temperature)
            except Exception as secondary_err:
                logger.error(f"Fallback provider {secondary_name} also failed: {secondary_err}.")
                raise RuntimeError(f"All LLM providers failed. Primary: {primary_err} | Fallback: {secondary_err}")

llm_router = LLMRouter()

