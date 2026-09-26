from __future__ import annotations

import ssl
import sys

import httpx


def _verify():
    context = ssl.create_default_context()
    try:
        import certifi

        context.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            for store in ("CA", "ROOT"):
                for cert, encoding, _trust in ssl.enum_certificates(store):
                    if encoding == "x509_asn":
                        context.load_verify_locations(cadata=cert)
        except Exception:
            pass
    return context


def openai_post(path: str, api_key: str, payload: dict, timeout: float = 45.0) -> dict:
    response = httpx.post(
        f"https://api.openai.com{path}",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
        verify=_verify(),
    )
    response.raise_for_status()
    return response.json()
