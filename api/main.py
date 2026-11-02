import os
import sys
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from uuid import UUID
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.database import LeadRepository, get_connection
from core.schemas import LeadRecord, PriorityTier, OutreachStatus
from core.orchestrator import master_orchestrator
from api.exporter import lead_exporter
from learning.memory_store import memory_store
from learning.evaluator import pipeline_evaluator
from core.logger import setup_logging, SCRAPER_LOG_PATH, ERRORS_LOG_PATH, UI_LOG_BUFFER
from core.memory_guard import get_memory_stats
from api.state import (
    SCRAPING_STATE,
    log_agent_activity,
    start_background_campaign,
    stop_background_campaign
)
from api.muse_routes import router as muse_router

app = FastAPI(
    title="Autonomous Lead Intelligence System API",
    description="Engineered to find, verify, score, and craft bespoke web-scraping outreach for B2B agencies.",
    version="2.0"
)

# CORS Middleware (Crucial for remote AI orchestration like MUSE AI and cloud webhooks)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount MUSE AI integration router
app.include_router(muse_router)

repo = LeadRepository()

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
def root(request: Request):
    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        return {
            "status": "online",
            "service": "Autonomous Multi-Agent Lead Gen System",
            "version": "2.0",
            "muse_api": {
                "manifest": "/api/v1/muse/manifest.json",
                "campaigns_start": "/api/v1/muse/campaigns/start",
                "campaigns_stop": "/api/v1/muse/campaigns/stop",
                "campaigns_status": "/api/v1/muse/campaigns/status",
                "leads": "/api/v1/muse/leads",
                "logs": "/api/v1/muse/logs",
                "telemetry": "/api/v1/muse/telemetry"
            }
        }
    index_file = Path("frontend/index.html")
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "status": "online",
        "service": "Autonomous Multi-Agent Lead Gen System",
        "endpoints": [
            "/api/campaigns", "/api/leads", "/api/export/csv", 
            "/api/export/xlsx", "/api/telemetry", "/api/status", "/dashboard",
            "/api/v1/muse/manifest.json"
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
        "deepseek_pool": {"active": deepseek_active, "total": 1, "model": settings.DEEPSEEK_MODEL},
        "memory": {**get_memory_stats(), "limit_mb": 512}
    }

@app.get("/api/telemetry")
def get_telemetry():
    from core.llm_router import llm_router
    from config.settings import settings
    
    is_running = SCRAPING_STATE.get("is_running", False)
    current_cid = getattr(master_orchestrator, "active_campaign_id", None) or SCRAPING_STATE.get("last_campaign_id")
    live_leads = getattr(master_orchestrator, "active_verified_leads", [])

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM leads")
    total_leads = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM scraped_domains")
    total_scraped_domains = c.fetchone()[0]

    if is_running:
        hot_leads_count = len(live_leads)
        qualified_count = len(live_leads)
        needs_review_count = 0
        rejected_count = 0
    elif current_cid:
        c.execute("SELECT COUNT(*) FROM leads WHERE campaign_id = ? AND overall_priority = 'Hot Lead'", (current_cid,))
        hot_leads_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM leads WHERE campaign_id = ? AND overall_priority IN ('Hot Lead', 'Qualified', 'High Potential')", (current_cid,))
        qualified_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM leads WHERE campaign_id = ? AND overall_priority = 'Needs Review'", (current_cid,))
        needs_review_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM leads WHERE campaign_id = ? AND overall_priority = 'Rejected'", (current_cid,))
        rejected_count = c.fetchone()[0]
    else:
        c.execute("SELECT COUNT(*) FROM leads WHERE overall_priority = 'Hot Lead'")
        hot_leads_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM leads WHERE overall_priority IN ('Hot Lead', 'Qualified', 'High Potential')")
        qualified_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM leads WHERE overall_priority = 'Needs Review'")
        needs_review_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM leads WHERE overall_priority = 'Rejected'")
        rejected_count = c.fetchone()[0]
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
        "total_leads": total_leads,
        "total_scraped_domains": total_scraped_domains,
        "groq_active": groq_active,
        "groq_total": len(llm_router.groq_pool.keys),
        "gemini_active": gemini_active,
        "gemini_total": len(llm_router.gemini_pool.keys),
        "deepseek_active": deepseek_active,
        "memory": {**get_memory_stats(), "limit_mb": 512}
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

@app.post("/api/campaigns/start")
def start_campaign_background(req: CampaignRequest):
    return start_background_campaign(req.prompt, target_count=req.target_count or 25)

@app.post("/api/campaigns/stop")
def stop_campaign():
    return stop_background_campaign()

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
    is_running = SCRAPING_STATE.get("is_running", False)
    if is_running and scope == "current":
        live_leads = getattr(master_orchestrator, "active_verified_leads", [])
        if live_leads:
            return list(reversed(live_leads))[:limit]

    target_campaign = campaign_id or getattr(master_orchestrator, "active_campaign_id", None) or SCRAPING_STATE.get("last_campaign_id")
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
    target_campaign = campaign_id or getattr(master_orchestrator, "active_campaign_id", None) or SCRAPING_STATE.get("last_campaign_id")

    if scope == "all":
        leads = repo.list_leads(priority=priority, limit=3000)
    else:
        # STRICT SESSION SCOPE: Only leads from the active or latest scraping run!
        live_leads = getattr(master_orchestrator, "active_verified_leads", [])
        if live_leads:
            leads = list(live_leads)
        elif SCRAPING_STATE.get("last_campaign_leads"):
            leads = list(SCRAPING_STATE["last_campaign_leads"])
        elif target_campaign:
            leads = repo.list_leads(priority=priority, campaign_id=target_campaign, limit=1000)
        else:
            conn = repo._get_conn()
            c = conn.cursor()
            c.execute("SELECT campaign_id FROM leads WHERE campaign_id IS NOT NULL ORDER BY collected_at DESC LIMIT 1")
            row = c.fetchone()
            conn.close()
            latest_cid = row["campaign_id"] if row else None
            leads = repo.list_leads(priority=priority, campaign_id=latest_cid, limit=1000) if latest_cid else []

    # STRICT EMAIL RULE: "email sara kono lead nibe na" & must not be rejected
    leads = [
        l for l in leads
        if (getattr(l, "verified_email", None) or getattr(l, "email", None))
        and str(l.verified_email or l.email).strip().lower() not in ["", "none", "nan", "null"]
        and "@" in str(l.verified_email or l.email)
        and getattr(l, "overall_priority", None) != PriorityTier.REJECTED
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
    target_campaign = campaign_id or getattr(master_orchestrator, "active_campaign_id", None) or SCRAPING_STATE.get("last_campaign_id")

    if scope == "all":
        leads = repo.list_leads(priority=priority, limit=3000)
    else:
        # STRICT SESSION SCOPE: Only leads from the active or latest scraping run!
        live_leads = getattr(master_orchestrator, "active_verified_leads", [])
        if live_leads:
            leads = list(live_leads)
        elif SCRAPING_STATE.get("last_campaign_leads"):
            leads = list(SCRAPING_STATE["last_campaign_leads"])
        elif target_campaign:
            leads = repo.list_leads(priority=priority, campaign_id=target_campaign, limit=1000)
        else:
            conn = repo._get_conn()
            c = conn.cursor()
            c.execute("SELECT campaign_id FROM leads WHERE campaign_id IS NOT NULL ORDER BY collected_at DESC LIMIT 1")
            row = c.fetchone()
            conn.close()
            latest_cid = row["campaign_id"] if row else None
            leads = repo.list_leads(priority=priority, campaign_id=latest_cid, limit=1000) if latest_cid else []

    # STRICT EMAIL RULE: "email sara kono lead nibe na" & must not be rejected
    leads = [
        l for l in leads
        if (getattr(l, "verified_email", None) or getattr(l, "email", None))
        and str(l.verified_email or l.email).strip().lower() not in ["", "none", "nan", "null"]
        and "@" in str(l.verified_email or l.email)
        and getattr(l, "overall_priority", None) != PriorityTier.REJECTED
    ]

    file_path = "exports/leads.xlsx"
    total_disc = SCRAPING_STATE.get("last_campaign_total_discovered", len(leads))
    lead_exporter.export_to_xlsx(leads, file_path, total_discovered=total_disc)
    return FileResponse(file_path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename="qualified_agency_leads.xlsx")

@app.get("/api/metrics")
def get_metrics():
    all_leads = repo.list_leads(limit=1000)
    return pipeline_evaluator.calculate_metrics(all_leads)

