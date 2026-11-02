import re
from typing import Optional
import phonenumbers

BLOCKED_ENTERPRISE_DOMAINS = {
    "att.com", "sbc.com", "att-mail.com", "mastercard.com", "aexp.com",
    "cvs.com", "prodigy.net", "worldpay.co.uk", "wa.me", "parceladvisor.ai",
    "sfdc.sbc.com", "microsoft.com", "apple.com", "amazon.com", "google.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "wikipedia.org", "w3.org", "schema.org", "adobe.com",
    "aflac.co.jp", "aflac.com", "ibanaccept.nl"
}

def is_valid_agency_domain(domain: Optional[str]) -> bool:
    """
    Strict Domain Validator:
    Rejects strings with spaces, asterisks (*), more than 1 subdomain level,
    or enterprise telecom/bank/mail server domains.
    """
    if not domain:
        return False
    d = str(domain).strip().lower()

    # Reject spaces, asterisks (*), or illegal url chars
    if any(c in d for c in [" ", "*", ",", ";", "<", ">", "\"", "'", "\\", "[", "]", "(", ")", "!"]):
        return False

    # Must contain a valid dot and TLD
    if "." not in d or d.startswith(".") or d.endswith("."):
        return False

    # Check blocked enterprise / bank / telecom domains
    for b in BLOCKED_ENTERPRISE_DOMAINS:
        if d == b or d.endswith("." + b):
            return False

    # Subdomain depth check:
    # A standard agency domain is `agency.com` (2 parts) or `sub.agency.com` (3 parts).
    # Double ccTLDs like `agency.co.uk` has 3 parts (0 subdomains), `sub.agency.co.uk` has 4 parts (1 subdomain).
    parts = d.split(".")
    if len(parts) >= 2 and parts[-2] in ["co", "com", "org", "net", "edu", "gov"] and len(parts[-1]) == 2:
        effective_depth = len(parts) - 2
    else:
        effective_depth = len(parts) - 1

    # Reject more than 1 subdomain level (e.g. mlpd10030.enaf.sfdc.sbc.com, stage.outbound.remedy.cli.mastercard.com)
    if effective_depth > 2:
        return False

    # Reject common internal mail routing / cloud subdomains
    if any(p in d for p in ["mail.", "smtp", "preview.", "advisor.ai", "cli.", "stage.", "test.", "dev."]):
        return False

    return True

def normalize_domain(url_or_domain: Optional[str]) -> Optional[str]:
    if not url_or_domain:
        return None
    d = str(url_or_domain).strip().lower()
    # Remove protocol
    d = re.sub(r"^https?://", "", d)
    # Remove www prefix
    d = re.sub(r"^www\.", "", d)
    # Remove paths, queries, fragments, ports, and trailing dots
    d = d.split("/")[0].split("?")[0].split("#")[0].split(":")[0].strip().strip(".")
    return d or None

def normalize_phone(raw_phone: Optional[str], default_region: str = "US") -> Optional[str]:
    if not raw_phone:
        return None
    clean = raw_phone.strip()
    try:
        parsed = phonenumbers.parse(clean, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass
    # Basic fallback if standard parser misses non-standard clean string
    digits = re.sub(r"\D", "", clean)
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return clean if len(digits) >= 10 else None

def normalize_agency_name_for_matching(name: Optional[str]) -> str:
    if not name:
        return ""
    clean = name.lower()
    # Strip common legal and marketing agency suffixes
    suffixes = [
        r"\bllc\b", r"\binc\b", r"\bltd\b", r"\bcorp\b", r"\bco\b",
        r"\bagency\b", r"\bmedia\b", r"\bdigital\b", r"\bgroup\b",
        r"\bmarketing\b", r"\bconsulting\b", r"\bsolutions\b", r"\bpartners\b"
    ]
    for suf in suffixes:
        clean = re.sub(suf, "", clean)
    # Strip punctuation and collapse whitespace
    clean = re.sub(r"[^\w\s]", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean

