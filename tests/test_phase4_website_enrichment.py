import pytest
from adapters.website_enrichment import WebsiteEnrichmentAgent, WebsiteSignalExtraction
from core.schemas import AgencyType

def test_link_discovery_and_text_extraction():
    agent = WebsiteEnrichmentAgent()
    sample_html = """
    <html>
        <head><title>Apex Outbound - B2B Lead Gen Agency</title></head>
        <body>
            <header><nav><a href="/about">About Us</a><a href="/services">Our Services</a><a href="https://google.com">Google</a></nav></header>
            <main>
                <h1>We generate qualified B2B appointments for SaaS companies.</h1>
                <p>Contact us at founder@apexoutbound.com or call 555-0192.</p>
                <img src="logo.png" />
            </main>
        </body>
    </html>
    """
    links = agent.discover_relevant_links("https://apexoutbound.com", sample_html)
    assert any("about" in l for l in links)
    assert any("services" in l for l in links)
    assert not any("google.com" in l for l in links)

    clean_text = agent.extract_clean_text(sample_html)
    assert "We generate qualified B2B appointments" in clean_text
    assert "<nav>" not in clean_text

    emails = agent.extract_emails(sample_html)
    assert "founder@apexoutbound.com" in emails

def test_llm_website_enrichment_mock_agency():
    agent = WebsiteEnrichmentAgent()
    # Test text payload representing an agency site
    agency_sample = """
    Apex Growth Agency
    Homepage: We are a premier cold email and outbound sales agency for commercial roofing and HVAC contractors.
    Services: We build targeted prospect lists and run high-converting cold email campaigns.
    About Us: Founded in 2020 by Marcus Vance, Managing Director. We have helped over 50 roofing contractors book $2M+ in commercial jobs.
    Contact: hello@apexgrowth.io
    """
    system_prompt = (
        "You are an agency reconnaissance agent. Extract structured signals from the website text. "
        "Strictly adhere to the schema."
    )
    from core.llm_router import llm_router, TaskType
    res = llm_router.route(
        task=TaskType.WEBSITE_PARSING,
        prompt=agency_sample,
        system_prompt=system_prompt,
        schema=WebsiteSignalExtraction
    )
    extraction: WebsiteSignalExtraction = res["data"]
    assert extraction.is_agency is True
    assert extraction.agency_type in (AgencyType.COLD_EMAIL, AgencyType.B2B_LEAD_GEN)
    assert any(ind.lower() in str(extraction.client_industries_served).lower() for ind in ["roofing", "hvac", "contractor"])
    assert "Marcus" in (extraction.decision_maker_name or "")
    print("\n[Enrichment Agent Extracted]:", extraction.model_dump())

def test_llm_website_enrichment_reject_b2c():
    agent = WebsiteEnrichmentAgent()
    b2c_sample = """
    Bob's Plumbing Services
    We fix clogged drains, water heaters, and leaky pipes in Denver, Colorado.
    Residential and commercial plumbing repairs. Call Bob at 303-555-1212.
    """
    system_prompt = (
        "You are an agency reconnaissance agent. Extract structured signals from the website text. "
        "Strictly adhere to the schema."
    )
    from core.llm_router import llm_router, TaskType
    res = llm_router.route(
        task=TaskType.WEBSITE_PARSING,
        prompt=b2c_sample,
        system_prompt=system_prompt,
        schema=WebsiteSignalExtraction
    )
    extraction: WebsiteSignalExtraction = res["data"]
    assert extraction.is_agency is False
    assert extraction.agency_type == AgencyType.NON_ICP
    print("\n[B2C Non-Agency Correctly Rejected]:", extraction.non_agency_reason)

