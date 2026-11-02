import os
import sys
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from uuid import UUID
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.database import LeadRepository, get_connection
from core.schemas import LeadRecord, PriorityTier, OutreachStatus
from core.orchestrator import master_orchestrator
from api.exporter import lead_exporter
from learning.memory_store import memory_store
from learning.evaluator import pipeline_evaluator
from core.logger import setup_logging, SCRAPER_LOG_PATH, ERRORS_LOG_PATH, UI_LOG_BUFFER

app = FastAPI(
    title="Autonomous Lead Intelligence System API",
    description="Engineered to find, verify, score, and craft bespoke web-scraping outreach for B2B agencies.",
    version="2.0"
)

repo = LeadRepository()

# Global Real-Time Scraping State
SCRAPING_STATE = {
    "is_running": False,
    "current_agent": "Idle",
    "prompt": "",
    "target_count": 250,
    "last_campaign_id": None,
    "last_campaign_leads": [],
    "last_event_time": "",
    "logs": UI_LOG_BUFFER
}

def log_agent_activity(agent: str, message: str, level: str = "INFO"):
    from datetime import datetime
    now_str = datetime.now().strftime("%H:%M:%S")
    SCRAPING_STATE["current_agent"] = agent
    SCRAPING_STATE["last_event_time"] = now_str
    
    # Broadcast to Python logger so it goes to scraper.log and errors.log
    mod_logger = logging.getLogger(agent)
    log_func = getattr(mod_logger, level.lower(), mod_logger.info)
    log_func(message)

# Mount frontend directory if it exists
frontend_dir = Path("frontend")
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory="frontend"), name="static")

class CampaignRequest(BaseModel):
    prompt: str
    target_count: Optional[int] = 10

class ApprovalRequest(BaseModel):
    notes: Optional[str] = None

class RejectionFeedbackRequest(BaseModel):
    reason: str
    mistake_rule: Optional[str] = None

class FeedbackInjectionRequest(BaseModel):
    rule: str
    agency_type: Optional[str] = "b2b_lead_gen"

@app.get("/")
def root():
    index_file = Path("frontend/index.html")
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "status": "online",
        "service": "Autonomous Multi-Agent Lead Gen System",
        "endpoints": [
            "/api/campaigns", "/api/leads", "/api/export/csv", 
            "/api/export/xlsx", "/api/telemetry", "/api/status", "/dashboard"
        ]
    }

@app.get("/dashboard")
def dashboard():
    index_file = Path("frontend/index.html")
    if index_file.exists():
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Dashboard index.html not found")

@app.get("/api/status")
def get_system_status():
    from core.llm_router import llm_router
    from config.settings import settings
    groq_active = sum(1 for k in llm_router.groq_pool.keys if k.is_available())
    gemini_active = sum(1 for k in llm_router.gemini_pool.keys if k.is_available())
    deepseek_active = 1 if settings.DEEPSEEK_API_KEY else 0
    return {
        "status": "online",
        "is_running": SCRAPING_STATE["is_running"],
        "current_agent": SCRAPING_STATE["current_agent"],
        "groq_pool": {"active": groq_active, "total": len(llm_router.groq_pool.keys)},
        "gemini_pool": {"active": gemini_active, "total": len(llm_router.gemini_pool.keys)},
        "deepseek_pool": {"active": deepseek_active, "total": 1, "model": settings.DEEPSEEK_MODEL}
    }

@app.get("/api/telemetry")
def get_telemetry():
    from core.llm_router import llm_router
    from config.settings import settings
    
    current_cid = SCRAPING_STATE.get("last_campaign_id")
    if current_cid:
        session_leads = repo.list_leads(campaign_id=current_cid, limit=1000)
        if not session_leads and SCRAPING_STATE.get("last_campaign_leads"):
            session_leads = SCRAPING_STATE["last_campaign_leads"]
    elif SCRAPING_STATE.get("last_campaign_leads"):
        session_leads = SCRAPING_STATE["last_campaign_leads"]
    else:
        session_leads = []

    all_leads = repo.list_leads(limit=5000)
    active_pool = session_leads if (current_cid or SCRAPING_STATE.get("is_running")) else all_leads

    hot_leads_count = sum(1 for l in active_pool if l.overall_priority == PriorityTier.HOT_LEAD or (l.verified_email and (l.total_score or l.opportunity_score or 0) >= 75))
    qualified_count = sum(1 for l in active_pool if l.overall_priority in (PriorityTier.HOT_LEAD, PriorityTier.QUALIFIED, PriorityTier.HIGH_POTENTIAL))
    needs_review_count = sum(1 for l in active_pool if l.overall_priority == PriorityTier.NEEDS_REVIEW)
    rejected_count = sum(1 for l in active_pool if l.overall_priority == PriorityTier.REJECTED)
    
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM scraped_domains")
    total_scraped_domains = c.fetchone()[0]
    conn.close()

    groq_active = sum(1 for k in llm_router.groq_pool.keys if k.is_available())
    gemini_active = sum(1 for k in llm_router.gemini_pool.keys if k.is_available())
    deepseek_active = 1 if settings.DEEPSEEK_API_KEY else 0

    return {
        "is_running": SCRAPING_STATE["is_running"],
        "current_agent": SCRAPING_STATE["current_agent"],
        "target_count": SCRAPING_STATE["target_count"],
        "hot_leads_count": hot_leads_count,
        "qualified_count": qualified_count,
        "needs_review_count": needs_review_count,
        "rejected_count": rejected_count,
        "total_leads": len(all_leads),
        "total_scraped_domains": total_scraped_domains,
        "groq_active": groq_active,
        "groq_total": len(llm_router.groq_pool.keys),
        "gemini_active": gemini_active,
        "gemini_total": len(llm_router.gemini_pool.keys),
        "deepseek_active": deepseek_active
    }

@app.get("/api/agent-activity")
def get_agent_activity(level: Optional[str] = None):
    telemetry = get_telemetry()
    logs = SCRAPING_STATE["logs"]
    if level:
        lvl_upper = level.upper()
        logs = [l for l in logs if l.get("level") == lvl_upper or (lvl_upper == "ERROR" and l.get("level") in ("ERROR", "CRITICAL", "WARNING"))]
    return {
        "is_running": SCRAPING_STATE["is_running"],
        "current_agent": SCRAPING_STATE["current_agent"],
        "prompt": SCRAPING_STATE["prompt"],
        "target_count": SCRAPING_STATE["target_count"],
        "hot_leads_count": telemetry["hot_leads_count"],
        "logs": logs[:60]
    }

@app.get("/api/logs/view")
def view_logs(kind: str = "scraper", lines: int = 100):
    """Returns the last N lines of scraper.log or errors.log."""
    target_path = ERRORS_LOG_PATH if kind == "errors" else SCRAPER_LOG_PATH
    if not target_path.exists():
        return {"status": "empty", "logs": []}
    try:
        with open(target_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            return {"status": "ok", "kind": kind, "logs": all_lines[-lines:]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/logs/download")
def download_logs(kind: str = "scraper"):
    """Download scraper.log or errors.log."""
    target_path = ERRORS_LOG_PATH if kind == "errors" else SCRAPER_LOG_PATH
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="Log file not created yet.")
    filename = "errors.log" if kind == "errors" else "scraper.log"
    return FileResponse(target_path, filename=filename, media_type="text/plain")

import threading
import traceback

def _background_scraper(prompt: str, target: int):
    SCRAPING_STATE["is_running"] = True
    SCRAPING_STATE["prompt"] = prompt
    SCRAPING_STATE["target_count"] = target
    SCRAPING_STATE["last_campaign_leads"] = []
    log_agent_activity("Master Orchestrator", f"Started scraping swarm targeting {target} hot leads for: '{prompt}'")
    try:
        result = master_orchestrator.run_campaign(prompt, target_count=target, on_event=log_agent_activity)
        SCRAPING_STATE["last_campaign_id"] = result["campaign_id"]
        SCRAPING_STATE["last_campaign_leads"] = result["leads"]
        SCRAPING_STATE["last_campaign_all_records"] = result.get("all_records", result["leads"])
        SCRAPING_STATE["last_campaign_total_discovered"] = result.get("total_discovered", len(result["leads"]))
        log_agent_activity("Master Orchestrator", f"Scraping campaign finished: {len(result['leads'])} verified leads with emails collected.")
    except Exception as e:
        err_trace = traceback.format_exc()
        log_agent_activity("Master Orchestrator", f"Campaign encountered error: {e}", level="ERROR")
        logging.getLogger("MasterOrchestrator").error(f"Full traceback:\n{err_trace}")
    finally:
        SCRAPING_STATE["is_running"] = False
        SCRAPING_STATE["current_agent"] = "Idle"

@app.post("/api/campaigns/start")
def start_campaign_background(req: CampaignRequest):
    if SCRAPING_STATE["is_running"]:
        return {"status": "already_running", "message": "Scraper is currently running."}
    
    t = threading.Thread(target=_background_scraper, args=(req.prompt, req.target_count or 250), daemon=True)
    t.start()
    return {"status": "started", "target_count": req.target_count or 250, "prompt": req.prompt}

@app.post("/api/campaigns/stop")
def stop_campaign():
    SCRAPING_STATE["is_running"] = False
    SCRAPING_STATE["current_agent"] = "Stopped"
    log_agent_activity("Master Orchestrator", "Scraper stopped by user.")
    return {"status": "stopped"}

@app.post("/api/database/reset")
def reset_database():
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM leads")
    c.execute("DELETE FROM scraped_domains")
    c.execute("DELETE FROM campaigns")
    conn.commit()
    conn.close()
    SCRAPING_STATE["logs"].clear()
    SCRAPING_STATE["last_campaign_leads"].clear()
    SCRAPING_STATE["last_campaign_id"] = None
    log_agent_activity("System", "Database cleared and reset to fresh state (0 leads).")
    return {"status": "reset", "leads": 0}

@app.post("/api/feedback")
def inject_feedback(req: FeedbackInjectionRequest):
    memory_store.add_penalty(
        trigger_reason="Operator Console Command",
        mistake_rule=req.rule,
        agency_type=req.agency_type,
        sample_data={"source": "Dashboard Live Stream"}
    )
    return {"status": "success", "rule": req.rule}

@app.post("/api/campaigns")
def trigger_campaign(req: CampaignRequest):
    result = master_orchestrator.run_campaign(req.prompt, target_count=req.target_count)
    SCRAPING_STATE["last_campaign_id"] = result["campaign_id"]
    SCRAPING_STATE["last_campaign_leads"] = result["leads"]
    SCRAPING_STATE["last_campaign_all_records"] = result.get("all_records", result["leads"])
    SCRAPING_STATE["last_campaign_total_discovered"] = result.get("total_discovered", len(result["leads"]))
    return {
        "campaign_id": result["campaign_id"],
        "plan": result["plan"],
        "metrics": result["metrics"],
        "leads_count": len(result["leads"])
    }

@app.get("/api/leads", response_model=List[LeadRecord])
def list_leads(
    priority: Optional[PriorityTier] = None,
    campaign_id: Optional[str] = None,
    scope: str = "current",
    limit: int = Query(default=100, ge=1, le=1000)
):
    target_campaign = campaign_id or SCRAPING_STATE.get("last_campaign_id")
    if scope == "current" and target_campaign:
        session_leads = repo.list_leads(priority=priority, campaign_id=target_campaign, limit=limit)
        if session_leads:
            return session_leads
        if SCRAPING_STATE.get("last_campaign_leads"):
            return SCRAPING_STATE["last_campaign_leads"][:limit]

    return repo.list_leads(priority=priority, limit=limit)

@app.get("/api/leads/{lead_id}", response_model=LeadRecord)
def get_lead(lead_id: UUID):
    lead = repo.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead

@app.post("/api/leads/{lead_id}/approve")
def approve_outreach_draft(lead_id: UUID, req: Optional[ApprovalRequest] = None):
    lead = repo.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    lead.outreach_status = OutreachStatus.APPROVED
    repo.save_lead(lead)

    # In-context reinforcement: Train model with golden example
    memory_store.add_golden_example(lead)
    return {"status": "approved", "lead_id": str(lead_id)}

@app.post("/api/leads/{lead_id}/reject")
def reject_lead_with_feedback(lead_id: UUID, req: RejectionFeedbackRequest):
    lead = repo.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    lead.overall_priority = PriorityTier.REJECTED
    lead.rejection_reason = req.reason
    lead.outreach_status = OutreachStatus.DRAFT
    repo.save_lead(lead)

    # In-context reinforcement: Log penalty mistake rule
    rule = req.mistake_rule or f"Avoid leads matching pattern: {req.reason}"
    memory_store.add_penalty(
        trigger_reason=req.reason,
        mistake_rule=rule,
        agency_type=lead.agency_type.value,
        sample_data={"business_name": lead.business_name, "website": lead.website}
    )
    return {"status": "rejected", "lead_id": str(lead_id), "penalty_rule_recorded": rule}

@app.get("/api/export/csv")
def export_csv(
    priority: Optional[PriorityTier] = None,
    campaign_id: Optional[str] = None,
    scope: str = "current"
):
    target_campaign = campaign_id or SCRAPING_STATE.get("last_campaign_id")

    if scope == "all":
        leads = repo.list_leads(priority=priority, limit=2000)
    elif target_campaign:
        leads = repo.list_leads(priority=priority, campaign_id=target_campaign, limit=1000)
        if not leads and SCRAPING_STATE.get("last_campaign_leads"):
            leads = SCRAPING_STATE["last_campaign_leads"]
    elif SCRAPING_STATE.get("last_campaign_leads"):
        leads = SCRAPING_STATE["last_campaign_leads"]
    else:
        leads = repo.list_leads(priority=priority, limit=1000)

    # STRICT EMAIL RULE: "email sara kono lead nibe na" & must not be rejected
    leads = [
        l for l in leads
        if (l.verified_email or l.email)
        and str(l.verified_email or l.email).strip().lower() not in ["", "none", "nan", "null"]
        and "@" in str(l.verified_email or l.email)
        and l.overall_priority != PriorityTier.REJECTED
    ]

    file_path = "exports/leads.csv"
    lead_exporter.export_to_csv(leads, file_path)
    return FileResponse(file_path, media_type="text/csv", filename="qualified_agency_leads.csv")

@app.get("/api/export/xlsx")
def export_xlsx(
    priority: Optional[PriorityTier] = None,
    campaign_id: Optional[str] = None,
    scope: str = "current"
):
    """
    Exports leads to Excel.
    Default scope='current': Only exports leads scraped during the current/latest session.
    scope='all': Exports full historical database.
    Strictly excludes leads without deliverable emails per user request: "email sara kono lead nibe na".
    """
    target_campaign = campaign_id or SCRAPING_STATE.get("last_campaign_id")

    if scope == "all":
        leads = repo.list_leads(priority=priority, limit=3000)
    elif SCRAPING_STATE.get("last_campaign_all_records"):
        leads = SCRAPING_STATE["last_campaign_all_records"]
    elif target_campaign:
        leads = repo.list_leads(priority=priority, campaign_id=target_campaign, limit=1000)
        if not leads and SCRAPING_STATE.get("last_campaign_leads"):
            leads = SCRAPING_STATE["last_campaign_leads"]
    elif SCRAPING_STATE.get("last_campaign_leads"):
        leads = SCRAPING_STATE["last_campaign_leads"]
    else:
        leads = repo.list_leads(priority=priority, limit=1000)

    file_path = "exports/leads.xlsx"
    total_disc = SCRAPING_STATE.get("last_campaign_total_discovered", len(leads))
    lead_exporter.export_to_xlsx(leads, file_path, total_discovered=total_disc)
    return FileResponse(file_path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename="qualified_agency_leads.xlsx")

@app.get("/api/metrics")
def get_metrics():
    all_leads = repo.list_leads(limit=1000)
    return pipeline_evaluator.calculate_metrics(all_leads)

