"""Organization name resolution from email domains.

Replicates the exact logic from the /su skill definition.
"""

PERSONAL_DOMAINS = frozenset({
    "gmail.com",
    "hotmail.com",
    "yahoo.com",
    "live.com",
    "outlook.com",
    "icloud.com",
    "aol.com",
    "protonmail.com",
    "me.com",
    "msn.com",
    "mail.com",
})


def resolve_org(email: str) -> str:
    """Derive a human-readable organization name from an email address.

    Rules (from su.md):
    - encircleapp.com -> "Encircle (internal)"
    - Corporate subdomains like ca.belfor.com -> "BELFOR Canada"
    - Personal email domains -> full email as org name
    - Unknown corporate domains -> capitalize domain name, strip TLD
    """
    if not email or "@" not in email:
        return "unknown"

    domain = email.split("@", 1)[1].lower()

    if domain in PERSONAL_DOMAINS:
        return email.lower()

    return _domain_to_org_name(domain)


def _domain_to_org_name(domain: str) -> str:
    """Convert a corporate email domain to a readable org name."""
    # Known mappings
    known = {
        "encircleapp.com": "Encircle (internal)",
        "ca.belfor.com": "BELFOR Canada",
        "us.belfor.com": "BELFOR US",
        "belfor.com": "BELFOR",
        "servicemaster.bc.ca": "ServiceMaster BC",
        "911restoration.com": "911 Restoration",
        "advantaclean.com": "AdvantaClean",
        "firstgeneraledm.ca": "First General Edmonton",
        "highlandrestoration.ca": "Highland Restoration",
        "winmarkelowna.com": "Winmar Kelowna",
        "smking.ca": "SM King",
        "smcalgary.com": "ServiceMaster Calgary",
        "restoration1.com": "Restoration 1",
        "servpro.com": "SERVPRO",
        "rfrg.com": "Rainbow International",
        "rainbowintl.com": "Rainbow International",
    }

    if domain in known:
        return known[domain]

    # Check if it's a subdomain of a known domain
    for known_domain, name in known.items():
        if domain.endswith("." + known_domain):
            # Extract subdomain prefix as qualifier
            prefix = domain[: -(len(known_domain) + 1)]
            return f"{name} ({prefix})"

    # Unknown corporate domain: capitalize the domain name, strip TLD
    parts = domain.split(".")
    if len(parts) >= 2:
        # Use the main domain part (before TLD)
        name_part = parts[-2] if len(parts) == 2 else parts[0]
        # Handle multi-part names like "rfconstruction.dki.ca"
        if len(parts) > 2 and parts[-1] in ("com", "ca", "net", "org", "co"):
            # e.g., rfconstruction.dki.ca -> "RF Construction DKI"
            name_parts = parts[:-1]  # everything except TLD
            return " ".join(_capitalize_part(p) for p in name_parts)
        return _capitalize_part(name_part)

    return domain


def _capitalize_part(part: str) -> str:
    """Capitalize a domain name part intelligently."""
    # All-lowercase short parts that look like acronyms
    if len(part) <= 4 and part.isalpha():
        return part.upper()
    # CamelCase or mixed case - leave as-is but capitalize first letter
    if any(c.isupper() for c in part[1:]):
        return part
    return part.capitalize()
