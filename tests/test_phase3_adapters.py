import pytest
from adapters.search_api_adapter import SearchApiAdapter
from adapters.google_maps_adapter import GoogleMapsAdapter
from adapters.directory_adapter import DirectoryAdapter
from adapters.base import RawLeadCandidate

def test_search_api_adapter():
    adapter = SearchApiAdapter()
    candidates = adapter.search("cold email agency", limit=3)
    assert len(candidates) > 0
    for c in candidates:
        assert isinstance(c, RawLeadCandidate)
        assert c.business_name
        assert c.source_name == "search_footprints"
        assert c.source_url.startswith("http")
        print("\n[Search Adapter Found]:", c.business_name, "| Domain:", c.website)

def test_google_maps_adapter():
    adapter = GoogleMapsAdapter()
    candidates = adapter.search_local("SEO agency", "Austin", limit=3)
    assert len(candidates) > 0
    for c in candidates:
        assert isinstance(c, RawLeadCandidate)
        assert c.business_name
        assert c.source_name == "google_maps"
        print("\n[Maps Adapter Found]:", c.business_name, "| Phone:", c.phone, "| City:", c.city)

def test_directory_adapter():
    adapter = DirectoryAdapter()
    candidates = adapter.search("lead generation agency", limit=3)
    assert len(candidates) > 0
    for c in candidates:
        assert isinstance(c, RawLeadCandidate)
        assert c.business_name
        assert c.source_name == "b2b_directories"
        print("\n[Directory Adapter Found]:", c.business_name, "| URL:", c.source_url)

