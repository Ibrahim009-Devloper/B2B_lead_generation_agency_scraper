import sqlite3
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from uuid import uuid4
from core.database import get_connection
from core.schemas import LeadRecord, AgencyType

logger = logging.getLogger("MemoryStore")

class MemoryStore:
    def __init__(self):
        pass

    def add_penalty(self, trigger_reason: str, mistake_rule: str, agency_type: Optional[str] = None, sample_data: Optional[Dict[str, Any]] = None):
        conn = get_connection()
        cursor = conn.cursor()
        item_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
        INSERT INTO feedback_memory (id, feedback_type, agency_type, trigger_reason, mistake_rule, sample_data, created_at)
        VALUES (?, 'penalty', ?, ?, ?, ?, ?)
        """, (item_id, agency_type, trigger_reason, mistake_rule, json.dumps(sample_data or {}), created_at))
        conn.commit()
        conn.close()
        logger.info(f"Logged penalty rule: '{mistake_rule}'")

    def add_golden_example(self, lead: LeadRecord):
        conn = get_connection()
        cursor = conn.cursor()
        item_id = str(uuid4())
        approved_at = datetime.now(timezone.utc).isoformat()
        vertical = lead.client_industries_served[0] if lead.client_industries_served else "B2B"
        cursor.execute("""
        INSERT INTO golden_examples (id, agency_type, business_name, vertical, scraping_pitch, lead_data, approved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            item_id, lead.agency_type.value, lead.business_name, vertical,
            lead.recommended_scraping_pitch or "", json.dumps(lead.model_dump(mode="json")), approved_at
        ))
        conn.commit()
        conn.close()
        logger.info(f"Saved golden example for {lead.business_name} ({vertical})")

    def get_penalties(self, limit: int = 5) -> List[str]:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT mistake_rule FROM feedback_memory WHERE feedback_type = 'penalty' ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [r["mistake_rule"] for r in rows]

    def get_golden_examples(self, agency_type: Optional[str] = None, limit: int = 3) -> List[Dict[str, Any]]:
        conn = get_connection()
        cursor = conn.cursor()
        if agency_type:
            cursor.execute("SELECT * FROM golden_examples WHERE agency_type = ? ORDER BY approved_at DESC LIMIT ?", (agency_type, limit))
        else:
            cursor.execute("SELECT * FROM golden_examples ORDER BY approved_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        examples = []
        for r in rows:
            examples.append({
                "business_name": r["business_name"],
                "vertical": r["vertical"],
                "scraping_pitch": r["scraping_pitch"],
                "data": json.loads(r["lead_data"] or "{}")
            })
        return examples

    def get_in_context_prompt_enhancement(self, agency_type: Optional[str] = None) -> str:
        """
        Dynamically constructs in-context learning instructions to append to LLM prompts.
        """
        penalties = self.get_penalties(limit=4)
        goldens = self.get_golden_examples(agency_type, limit=2)
        
        sections = []
        if penalties:
            rules_str = "\n".join([f"- DO NOT: {p}" for p in penalties])
            sections.append(f"CRITICAL AVOIDANCE RULES (Learned from previous mistakes):\n{rules_str}")

        if goldens:
            examples_str = "\n".join([
                f"- Example: {g['business_name']} ({g['vertical']}) -> Pitch: {g['scraping_pitch']}"
                for g in goldens
            ])
            sections.append(f"GOLDEN EXAMPLES OF HIGH-CONVERTING SCRAPING HOOKS:\n{examples_str}")

        return "\n\n".join(sections)

memory_store = MemoryStore()

