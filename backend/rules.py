"""The KYC verification rule set used for bulk uploads.

Only the five checks selected for the bulk-upload pipeline are included:
KYC_01, KYC_02, KYC_04, KYC_05, KYC_09.
"""

RULES = [
    {
        "id": "KYC_01",
        "flag": "Incomplete KYC",
        "process_step": "KYC Form Review",
        "severity": "High",
        "applies_to": ["application_form"],
        "description": "Check completeness of mandatory KYC form fields.",
        "fail_when": (
            "Any mandatory field — Full Name, Date of Birth, PAN / Tax ID, "
            "Residential Address, or Risk Category — is blank, empty, missing, "
            "or left as a placeholder on the application form."
        ),
    },
    {
        "id": "KYC_02",
        "flag": "Poor Documentation",
        "process_step": "KYC Form Review",
        "severity": "Medium",
        "applies_to": ["application_form"],
        "description": "Validate the quality of the customer write-up / narrative fields.",
        "fail_when": (
            "A free-text write-up field (e.g. Purpose of Account, Customer "
            "Background) is very short / below a meaningful length, OR contains "
            'generic filler such as "NA", "N/A", "Same", "Same as above", "-", '
            "or other non-informative text."
        ),
    },
    {
        "id": "KYC_04",
        "flag": "Invalid Document",
        "process_step": "ID & Verification",
        "severity": "High",
        "applies_to": ["identity_document"],
        "description": "Validate identity document authenticity by expiry date and format.",
        "fail_when": (
            "The identity document's expiry date is earlier than today's date "
            "(expired), OR a key date is missing or in an invalid / unreadable "
            "format."
        ),
    },
    {
        "id": "KYC_05",
        "flag": "Data Mismatch",
        "process_step": "ID & Verification",
        "severity": "High",
        "applies_to": ["application_form", "identity_document"],
        "description": "Cross-check name consistency between the KYC form and the ID document.",
        "fail_when": (
            "The customer name on the application form does not match the name "
            "on the identity document — spelling differences, a different "
            "surname, transposed names, etc. Differences only in letter case or "
            "extra spacing are NOT a mismatch."
        ),
    },
    {
        "id": "KYC_09",
        "flag": "Incomplete Profile",
        "process_step": "Customer Info",
        "severity": "Medium",
        "applies_to": ["application_form"],
        "description": "Validate completeness of key customer profile attributes.",
        "fail_when": (
            "Any of Industry, Source of Wealth, or Business Activity is "
            "missing, blank, or non-informative on the application form."
        ),
    },
]

RULES_BY_ID = {r["id"]: r for r in RULES}


def rules_prompt_block() -> str:
    """Render the rule set as a text block for the LLM system prompt."""
    lines = []
    for r in RULES:
        lines.append(
            f"[{r['id']}] {r['flag']}  (Severity: {r['severity']})\n"
            f"  Process step : {r['process_step']}\n"
            f"  Applies to   : {', '.join(r['applies_to'])}\n"
            f"  Check        : {r['description']}\n"
            f"  FAIL when    : {r['fail_when']}"
        )
    return "\n\n".join(lines)
