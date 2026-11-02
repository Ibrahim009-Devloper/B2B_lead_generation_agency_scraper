from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class RawLeadCandidate(BaseModel):
    business_name: str
    website: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    source_name: str
    source_url: str
    snippet: Optional[str] = None
    raw_data: Dict[str, Any] = Field(default_factory=dict)

class SourceAdapter(ABC):
    def __init__(self, name: str, source_type: str):
        self.name = name
        self.source_type = source_type

    @abstractmethod
    def search(self, query: str, limit: int = 20) -> List[RawLeadCandidate]:
        """
        Executes a search query and returns candidate leads with source provenance.
        """
        pass

