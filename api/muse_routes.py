import os
from typing import Optional, List, Dict, Any
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query, Header, Request, Depends, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from core.database import LeadRepository, get_connection
from core.schemas import LeadRecord, PriorityTier, OutreachStatus, AgencyType
from core.orchestrator import master_orchestrator
from core.logger import SCRAPER_LOG_PATH, ERRORS_LOG_PATH
from api.exporter import lead_exporter
from learning.memory_store import memory_store
from core.memory_guard import get_memory_stats
from api.state import (
    SCRAPING_STATE,
    log_agent_activity,
    start_background_campaign,
    stop_background_campaign
)

router = APIRouter(prefix="/api/v1/muse", tags=["MUSE AI Integration"])
repo = LeadRepository()

# Optional Security Dependency
def verify_muse_auth(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    """
    Checks API Key if MUSE_API_KEY or API_KEY environment variable is configured.
    Supports either 'X-API-Key: <key>' or 'Authorization: Bearer <key>'.
    If no key is configured on the server, requests are openly permitted.
    """
    configured_key = os.getenv("MUSE_API_KEY") or os.getenv("API_KEY")
    if not configured_key:
        return True # Permissive default when not configured

    token = None
    if x_api_key:
        token = x_api_key.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    
    if token != configured_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key for MUSE AI endpoint. Provide 'X-API-Key' or 'Authorization: Bearer <key>'."
        )
    return True

# Request & Response Schemas
class MuseCampaignStartRequest(BaseModel):
    prompt: str = Field(..., description="Target search prompt, e.g. 'B2B Lead Generation agencies in USA' or 'Cold Email outbound agencies'")
    target_count: Optional[int] = Field(25, ge=1, le=500, description="Target number of qualified leads with verified emails")
    agency_types: Optional[List[str]] = Field(None, description="Optional target niches, e.g. ['b2b_lead_gen', 'cold_email', 'local_seo']")
    geo: Optional[str] = Field(None, description="Geographic filter, e.g. 'USA', 'UK', 'Remote'")
    webhook_url: Optional[str] = Field(None, description="Optional callback URL. If provided, the system will POST all verified leads directly to this URL upon completion, completely eliminating the need for periodic polling and saving LLM tokens.")

class MuseFeedbackRequest(BaseModel):
    rule: str = Field(..., description="Rule or negative signal to teach the model, e.g. 'Reject agencies focused solely on influencer PR'")
    agency_type: Optional[str] = Field("b2b_lead_gen", description="Target agency classification")
    action: Optional[str] = Field("penalty", description="'penalty' to blacklist or 'golden_example' to reinforce")

# 1. Manifest / AI Action Registry Endpoint
@router.get("/manifest.json")
@router.get("/actions")
def get_muse_manifest(request: Request):
    """
    Returns the complete AI Action Manifest and Tool Catalog for MUSE AI.
    MUSE AI can consume this manifest to automatically register tools for autonomous remote orchestration.
    """
    base_url = str(request.base_url).rstrip("/")
    return {
        "schema_version": "1.0.0",
        "name": "B2B Lead Generation & Autonomous Scraping Swarm",
        "description": "High-performance Python-first autonomous lead generation system with DNS MX verification and AI verification. Discovers, cleans, and scores verified B2B leads with real deliverable emails.",
        "server_base_url": base_url,
        "auth": {
            "type": "api_key",
            "header": "X-API-Key or Authorization: Bearer <token>",
            "configured": bool(os.getenv("MUSE_API_KEY") or os.getenv("API_KEY"))
        },
        "tools": [
            {
                "id": "start_campaign",
                "name": "Start Scraping Campaign",
                "description": "Launch an autonomous scraping swarm to discover, multi-page crawl, verify, and summarize B2B leads.",
                "method": "POST",
                "endpoint": f"{base_url}/api/v1/muse/campaigns/start",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Search target description (e.g. 'B2B lead generation agencies in USA')"},
                        "target_count": {"type": "integer", "default": 25, "description": "Number of verified hot leads with deliverable emails to harvest"},
                        "agency_types": {"type": "array", "items": {"type": "string"}, "description": "Optional agency categories"},
                        "geo": {"type": "string", "description": "Optional target country or region"},
                        "webhook_url": {"type": "string", "description": "Optional callback URL to receive the complete leads payload automatically upon finish (0 AI polling token cost)"}
                    },
                    "required": ["prompt"]
                }
            },
            {
                "id": "stop_campaign",
                "name": "Stop Scraping Campaign",
                "description": "Immediately halts the active scraping swarm and stops all background workers.",
                "method": "POST",
                "endpoint": f"{base_url}/api/v1/muse/campaigns/stop",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "id": "get_campaign_status",
                "name": "Get Campaign Status",
                "description": "Check if the scraper is running, get current agent stage, progress percentage, and lead count.",
                "method": "GET",
                "endpoint": f"{base_url}/api/v1/muse/campaigns/status",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "id": "get_live_logs",
                "name": "Read System Logs",
                "description": "Retrieve the latest execution logs (scraper.log or errors.log) for real-time observation and error analysis.",
                "method": "GET",
                "endpoint": f"{base_url}/api/v1/muse/logs",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["scraper", "errors"], "default": "scraper"},
                        "lines": {"type": "integer", "default": 50, "description": "Number of trailing log lines to return (1-500)"},
                        "level": {"type": "string", "description": "Optional level filter: INFO, WARNING, ERROR"}
                    }
                }
            },
            {
                "id": "get_verified_leads",
                "name": "Get Verified Leads",
                "description": "Retrieve qualified B2B leads with 100% verified deliverable emails, decision-maker details, complete business summaries, and ready cold emails.",
                "method": "GET",
                "endpoint": f"{base_url}/api/v1/muse/leads",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scope": {"type": "string", "enum": ["current", "all"], "default": "current", "description": "Fetch only the current session or all past database leads"},
                        "limit": {"type": "integer", "default": 50, "description": "Maximum number of leads to return"},
                        "priority": {"type": "string", "description": "Filter by priority tier (e.g. 'Hot Lead', 'Qualified')"}
                    }
                }
            },
            {
                "id": "get_lead_details",
                "name": "Get Lead Dossier by ID",
                "description": "Retrieve the complete detailed intelligence dossier for a single lead by its UUID.",
                "method": "GET",
                "endpoint": f"{base_url}/api/v1/muse/leads/{{lead_id}}",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lead_id": {"type": "string", "description": "UUID of the lead"}
                    },
                    "required": ["lead_id"]
                }
            },
            {
                "id": "get_telemetry",
                "name": "Get System Telemetry",
                "description": "Inspect system health, active LLM router key pools (Groq, Gemini, DeepSeek), rotating proxies, and database metrics.",
                "method": "GET",
                "endpoint": f"{base_url}/api/v1/muse/telemetry",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "id": "submit_feedback",
                "name": "Submit Learning Feedback",
                "description": "Inject learning feedback or penalty rules into memory store to refine agency targeting and eliminate false positives.",
                "method": "POST",
                "endpoint": f"{base_url}/api/v1/muse/feedback",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "rule": {"type": "string", "description": "Rule to enforce"},
                        "agency_type": {"type": "string", "default": "b2b_lead_gen"}
                    },
                    "required": ["rule"]
                }
            }
        ]
    }

# 2. Campaign Management Endpoints
@router.post("/campaigns/start", dependencies=[Depends(verify_muse_auth)])
@router.post("/campaigns/start/", dependencies=[Depends(verify_muse_auth)])
def muse_start_campaign(req: MuseCampaignStartRequest):
    """
    Launch an autonomous background scraping campaign from MUSE AI.
    """
    effective_prompt = req.prompt
    if req.geo and req.geo.lower() not in effective_prompt.lower():
        effective_prompt = f"{effective_prompt} in {req.geo}"
    
    target = req.target_count or 25
    result = start_background_campaign(effective_prompt, target_count=target, webhook_url=req.webhook_url)
    
    return {
        "status": result["status"],
        "message": result["message"],
        "prompt": effective_prompt,
        "target_count": target,
        "webhook_url": req.webhook_url,
        "is_running": SCRAPING_STATE["is_running"]
    }

@router.post("/campaigns/stop", dependencies=[Depends(verify_muse_auth)])
@router.post("/campaigns/stop/", dependencies=[Depends(verify_muse_auth)])
def muse_stop_campaign():
    """
    Immediately stops the active campaign and signals all background workers to abort.
    """
    result = stop_background_campaign()
    return result

@router.get("/campaigns/status", dependencies=[Depends(verify_muse_auth)])
@router.get("/campaigns/status/", dependencies=[Depends(verify_muse_auth)])
def muse_get_campaign_status():
    """
    Returns the real-time execution status of the scraper for MUSE AI.
    """
    is_running = SCRAPING_STATE.get("is_running", False)
    target_count = SCRAPING_STATE.get("target_count", 25)
    live_leads = getattr(master_orchestrator, "active_verified_leads", [])
    
    collected_count = len(live_leads) if is_running else len(SCRAPING_STATE.get("last_campaign_leads", []))
    progress_pct = round((collected_count / target_count) * 100, 1) if target_count > 0 else 0.0

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM scraped_domains")
    total_scraped_domains = c.fetchone()[0]
    conn.close()

    return {
        "status": "active" if is_running else "idle",
        "is_running": is_running,
        "current_agent": SCRAPING_STATE.get("current_agent", "Idle"),
        "prompt": SCRAPING_STATE.get("prompt", ""),
        "target_count": target_count,
        "collected_hot_leads": collected_count,
        "progress_percent": min(100.0, progress_pct),
        "total_scraped_domains": total_scraped_domains,
        "last_event_time": SCRAPING_STATE.get("last_event_time", ""),
        "campaign_id": getattr(master_orchestrator, "active_campaign_id", None) or SCRAPING_STATE.get("last_campaign_id"),
        "memory": {**get_memory_stats(), "limit_mb": 512}
    }

# 3. Live Logs & Diagnostics Endpoints
@router.get("/logs", dependencies=[Depends(verify_muse_auth)])
@router.get("/logs/", dependencies=[Depends(verify_muse_auth)])
def muse_get_logs(
    kind: str = Query("scraper", pattern="^(scraper|errors)$", description="Which log file to inspect"),
    lines: int = Query(50, ge=1, le=500, description="Number of recent log lines to return"),
    level: Optional[str] = Query(None, description="Filter lines containing this log level (e.g. ERROR, WARNING, INFO)")
):
    """
    Returns trailing lines from scraper.log or errors.log so MUSE AI can analyze execution details or debug issues.
    """
    target_path = ERRORS_LOG_PATH if kind == "errors" else SCRAPER_LOG_PATH
    if not target_path.exists():
        return {
            "status": "empty",
            "kind": kind,
            "total_lines": 0,
            "logs": [],
            "summary": "Log file not created yet."
        }
    
    try:
        with open(target_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = [line.rstrip() for line in f.readlines() if line.strip()]
        
        if level:
            lvl_upper = level.upper()
            all_lines = [l for l in all_lines if lvl_upper in l]

        selected_lines = all_lines[-lines:]
        error_count = sum(1 for l in selected_lines if "ERROR" in l or "CRITICAL" in l)

        return {
            "status": "ok",
            "kind": kind,
            "requested_lines": lines,
            "returned_lines": len(selected_lines),
            "error_count_in_batch": error_count,
            "logs": selected_lines
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {str(e)}")

@router.get("/activity", dependencies=[Depends(verify_muse_auth)])
@router.get("/activity/", dependencies=[Depends(verify_muse_auth)])
def muse_get_live_activity(limit: int = Query(50, ge=1, le=100)):
    """
    Returns the real-time event buffer captured by the orchestrator (agent step-by-step actions).
    """
    buffer = SCRAPING_STATE.get("logs", [])
    recent = buffer[:limit]
    return {
        "status": "ok",
        "current_agent": SCRAPING_STATE.get("current_agent", "Idle"),
        "is_running": SCRAPING_STATE.get("is_running", False),
        "count": len(recent),
        "events": recent
    }

# 4. Leads & Intelligence Retrieval Endpoints
@router.get("/leads", dependencies=[Depends(verify_muse_auth)])
@router.get("/leads/", dependencies=[Depends(verify_muse_auth)])
def muse_get_leads(
    scope: str = Query("current", pattern="^(current|all)$", description="Scope of leads: 'current' (latest session) or 'all' (entire database)"),
    limit: int = Query(50, ge=1, le=1000, description="Max leads to return"),
    priority: Optional[str] = Query(None, description="Filter priority (e.g. 'Hot Lead', 'Qualified')"),
    min_score: int = Query(0, ge=0, le=100, description="Minimum opportunity score threshold")
):
    """
    Retrieve qualified B2B leads formatted according to the 12-column GEMINI Master standard.
    Excludes synthetic/guessed emails; delivers only DNS MX verified deliverable emails.
    """
    is_running = SCRAPING_STATE.get("is_running", False)
    target_campaign = getattr(master_orchestrator, "active_campaign_id", None) or SCRAPING_STATE.get("last_campaign_id")

    leads: List[LeadRecord] = []
    if scope == "current":
        if is_running and getattr(master_orchestrator, "active_verified_leads", None):
            leads = list(master_orchestrator.active_verified_leads)
        elif target_campaign:
            leads = repo.list_leads(campaign_id=target_campaign, limit=limit)
        elif SCRAPING_STATE.get("last_campaign_leads"):
            leads = list(SCRAPING_STATE["last_campaign_leads"])
        else:
            conn = repo._get_conn()
            c = conn.cursor()
            c.execute("SELECT campaign_id FROM leads WHERE campaign_id IS NOT NULL ORDER BY collected_at DESC LIMIT 1")
            row = c.fetchone()
            conn.close()
            latest_cid = row["campaign_id"] if row else None
            leads = repo.list_leads(campaign_id=latest_cid, limit=limit) if latest_cid else []
    else:
        leads = repo.list_leads(limit=limit)

    # Filter strictly for valid emails and non-rejected status
    valid_leads: List[LeadRecord] = []
    for l in leads:
        email = getattr(l, "verified_email", None) or getattr(l, "email", None)
        if not email or "@" not in str(email) or str(email).strip().lower() in ["none", "nan", "null", ""]:
            continue
        if getattr(l, "overall_priority", None) == PriorityTier.REJECTED:
            continue
        if priority and hasattr(l, "overall_priority") and l.overall_priority:
            p_val = l.overall_priority.value if hasattr(l.overall_priority, "value") else str(l.overall_priority)
            if priority.lower() not in p_val.lower():
                continue
        score = getattr(l, "opportunity_score", 0) or getattr(l, "total_score", 0) or 0
        if score < min_score:
            continue
        valid_leads.append(l)

    # Convert leads to standard 12-column GEMINI Master payload
    formatted_leads = []
    for l in valid_leads[:limit]:
        row = lead_exporter._lead_to_row(l)
        row["lead_id"] = str(l.lead_id)
        formatted_leads.append(row)

    return {
        "status": "ok",
        "scope": scope,
        "count": len(formatted_leads),
        "leads": formatted_leads
    }

@router.get("/leads/{lead_id}", dependencies=[Depends(verify_muse_auth)])
def muse_get_lead_by_id(lead_id: UUID):
    """
    Returns full raw dossier and AI evaluation details for a specific lead.
    """
    lead = repo.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead with id '{lead_id}' not found.")
    
    clean_row = lead_exporter._lead_to_row(lead)
    return {
        "status": "ok",
        "lead_id": str(lead.lead_id),
        "summary_row": clean_row,
        "full_record": lead.model_dump()
    }

@router.get("/export", dependencies=[Depends(verify_muse_auth)])
@router.get("/export/", dependencies=[Depends(verify_muse_auth)])
def muse_export_leads(
    format: str = Query("json", pattern="^(json|xlsx|csv)$", description="Export format"),
    scope: str = Query("current", pattern="^(current|all)$", description="Scope of export")
):
    """
    Exports leads as JSON, Excel (.xlsx), or CSV.
    """
    if format == "json":
        data = muse_get_leads(scope=scope, limit=1000)
        return JSONResponse(content=data)
    elif format == "xlsx":
        from api.main import export_xlsx
        return export_xlsx(scope=scope)
    else:
        from api.main import export_csv
        return export_csv(scope=scope)

# 5. System Telemetry & Health
@router.get("/telemetry", dependencies=[Depends(verify_muse_auth)])
@router.get("/telemetry/", dependencies=[Depends(verify_muse_auth)])
def muse_get_telemetry():
    """
    Telemetry and health diagnostics for MUSE AI to inspect system capacity and resource pools.
    """
    from core.llm_router import llm_router
    from config.settings import settings
    from core.proxy_rotator import proxy_rotator

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM leads")
    total_leads_in_db = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM scraped_domains")
    total_scraped_domains = c.fetchone()[0]
    conn.close()

    groq_active = sum(1 for k in llm_router.groq_pool.keys if k.is_available())
    gemini_active = sum(1 for k in llm_router.gemini_pool.keys if k.is_available())
    deepseek_active = 1 if settings.DEEPSEEK_API_KEY else 0

    return {
        "status": "online",
        "service": "Autonomous Multi-Agent Lead Gen System",
        "version": "2.0",
        "environment": os.getenv("ENVIRONMENT", "production"),
        "is_running": SCRAPING_STATE["is_running"],
        "current_agent": SCRAPING_STATE["current_agent"],
        "total_leads_in_db": total_leads_in_db,
        "total_scraped_domains": total_scraped_domains,
        "proxies": {
            "total_configured": len(proxy_rotator.proxies),
            "rotation_strategy": "Round-Robin Failover"
        },
        "llm_key_pools": {
            "groq": {"active": groq_active, "total": len(llm_router.groq_pool.keys)},
            "gemini": {"active": gemini_active, "total": len(llm_router.gemini_pool.keys)},
            "deepseek": {"active": deepseek_active, "total": 1 if settings.DEEPSEEK_API_KEY else 0}
        },
        "memory": {**get_memory_stats(), "limit_mb": 512}
    }

# 6. Reinforcement Feedback
@router.post("/feedback", dependencies=[Depends(verify_muse_auth)])
@router.post("/feedback/", dependencies=[Depends(verify_muse_auth)])
def muse_submit_feedback(req: MuseFeedbackRequest):
    """
    Inject reinforcement learning rules into the memory store from MUSE AI.
    """
    memory_store.add_penalty(
        trigger_reason="MUSE AI Agent Instruction",
        mistake_rule=req.rule,
        agency_type=req.agency_type,
        sample_data={"source": "MUSE AI REST Call"}
    )
    return {
        "status": "success",
        "rule_injected": req.rule,
        "agency_type": req.agency_type,
        "message": "Rule successfully saved to in-context memory store."
    }
