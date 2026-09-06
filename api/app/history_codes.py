"""Static reference descriptions for FCC ULS Amateur Service history (HS)
record log codes, so the UI can render a human-readable explanation of what
each history entry means instead of a bare code.

Codes observed in the HS file follow the pattern <area><action><sub-action>.
This is a best-effort mapping of the codes we actually emit/encounter; unknown
codes fall back to displaying the raw code itself.
"""

HISTORY_CODE_DESCRIPTIONS: dict[str, str] = {
    "LIREN": "License renewed",
    "LIISS": "License issued",
    "SYSGRT": "System-granted (auto-grant)",
    "LIAUA": "Administrative update",
    "LIEXP": "License expired",
    "LIMOD": "License modified",
    "LICAN": "License cancelled",
    "LITIN": "License term initiated",
    "VANGRT": "Vanity callsign granted",
    "LTSFRN": "License transferred (FRN change)",
    "COR": "Correction applied",
    "ESCFRN": "FRN change (estate/successor)",
    "AUTHPR": "Authorization printed",
    "RCDUP": "Record duplicated",
    "ESUFRN": "FRN update (estate/successor)",
    "INTDUP": "Internal duplicate record",
    "LTSFND": "License transfer - new FRN (donor)",
    "LTSFNR": "License transfer - new FRN (recipient)",
    "LITERM": "License terminated",
    "ESCFND": "Estate/successor change (donor)",
    "EFCFRN": "FRN change",
    "ESCFNR": "Estate/successor change (recipient)",
    "ESUFND": "Estate/successor update (donor)",
    "ESUFNR": "Estate/successor update (recipient)",
    "PLAUPR": "Pleading/upfront review",
    "EFUFRN": "FRN update",
    "EFCFNR": "FRN change (recipient)",
    "EFCFND": "FRN change (donor)",
    "EFUFND": "FRN update (donor)",
    "EFUFNR": "FRN update (recipient)",
    "CORADD": "Correction - address",
    "GRREV": "Grant revoked",
    "LICARE": "License cancelled/reinstated",
    "MTSCOM": "Master trustee comment",
    "LTFFRN": "License transfer FRN",
    "LITERE": "License terminated/reinstated",
    "LETERM": "License term ended",
    "LIRTAC": "License returned to active",
    "LETCAS": "License term case",
    "LIRMD": "License remark deleted",
}


def describe_history_code(code: str | None) -> str:
    """Return a human-readable description for an HS log code."""
    if not code:
        return ""
    return HISTORY_CODE_DESCRIPTIONS.get(code.strip().upper(), code)
