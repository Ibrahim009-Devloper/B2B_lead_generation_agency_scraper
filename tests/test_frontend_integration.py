import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

def test_frontend_html_file_exists():
    html_path = Path("frontend/index.html")
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")
    assert len(content) > 50000
    assert "LEAD-PULSE 3D" in content
    assert "Swarm Cockpit 3D" in content
    assert "threejs-container-ANIMATION_2" in content
    assert "SCOUT-X" in content
    assert "VIPER" in content
    assert "VERITAS" in content
    assert "ARBITER" in content
    assert "ECHO" in content
    assert "NEXUS" in content
    assert "/api/campaigns" in content
    assert "/api/leads" in content
    assert "/api/telemetry" in content

def test_dashboard_endpoint():
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert "LEAD-PULSE 3D" in res.text

def test_root_browser_request_returns_html():
    res = client.get("/", headers={"Accept": "text/html,application/xhtml+xml"})
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert "LEAD-PULSE 3D" in res.text

def test_api_status_endpoint():
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert data["active_nodes"] == 48
    assert "groq_pool" in data
    assert "gemini_pool" in data

def test_api_telemetry_endpoint():
    res = client.get("/api/telemetry")
    assert res.status_code == 200
    data = res.json()
    assert data["zero_token_rejections"] > 0
    assert data["cooldown_skips"] >= 0
    assert data["hot_leads_count"] >= 0
    assert data["groq_total"] >= 2
    assert data["gemini_total"] >= 2

def test_api_runtime_feedback_injection():
    res = client.post("/api/feedback", json={
        "rule": "Avoid agencies offering pure B2C social media management without lead scraping demand.",
        "agency_type": "digital_marketing"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"

