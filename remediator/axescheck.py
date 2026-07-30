#!/usr/bin/env python3
"""
axesCheck (check.axes4.com) PDF Accessibility Checker API Client & MCP Module.
Solves ALTCHA proof-of-work challenges in <1ms and posts PDFs to check.axes4.com/api/upload.
"""

import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def solve_altcha_challenge(challenge_data: dict) -> str:
    """
    Solves ALTCHA SHA-256 proof-of-work challenge in <1ms.
    """
    algorithm = challenge_data.get("algorithm", "SHA-256")
    challenge = challenge_data.get("challenge", "")
    salt = challenge_data.get("salt", "")
    signature = challenge_data.get("signature", "")
    max_num = challenge_data.get("maxNumber", 50000)

    for num in range(max_num + 1):
        candidate = f"{salt}{num}".encode("utf-8")
        if hashlib.sha256(candidate).hexdigest() == challenge:
            payload = {
                "algorithm": algorithm,
                "challenge": challenge,
                "number": num,
                "salt": salt,
                "signature": signature,
            }
            return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

    return ""


def audit_pdf_axescheck(pdf_path: str, language: str = "en", timeout: float = 20.0) -> dict:
    """
    Submits a PDF file to check.axes4.com API and returns the full accessibility audit report.
    """
    if not os.path.exists(pdf_path):
        return {"success": False, "error": f"File not found: {pdf_path}"}

    # 1. Fetch ALTCHA challenge
    try:
        req_ch = urllib.request.Request(
            "https://check.axes4.com/api/challenge",
            headers={"User-Agent": "ADA-PDF-Remediator/1.0"},
        )
        with urllib.request.urlopen(req_ch, timeout=timeout) as resp:
            challenge_data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"success": False, "error": f"Failed to fetch challenge: {e}"}

    # 2. Solve challenge
    altcha_payload = solve_altcha_challenge(challenge_data)
    if not altcha_payload:
        return {"success": False, "error": "Failed to solve ALTCHA challenge."}

    # 3. Upload PDF file via multipart form-data
    try:
        boundary = "----WebKitFormBoundary" + hashlib.md5(os.urandom(16)).hexdigest()
        file_bytes = Path(pdf_path).read_bytes()
        filename = os.path.basename(pdf_path)

        body: list[bytes] = []
        # file
        body.append(f"--{boundary}\r\n".encode("utf-8"))
        body.append(
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(
                "utf-8"
            )
        )
        body.append(b"Content-Type: application/pdf\r\n\r\n")
        body.append(file_bytes)
        body.append(b"\r\n")

        # token
        body.append(f"--{boundary}\r\n".encode("utf-8"))
        body.append(b'Content-Disposition: form-data; name="token"\r\n\r\n')
        body.append(altcha_payload.encode("utf-8"))
        body.append(b"\r\n")

        # language
        body.append(f"--{boundary}\r\n".encode("utf-8"))
        body.append(b'Content-Disposition: form-data; name="language"\r\n\r\n')
        body.append(language.encode("utf-8"))
        body.append(b"\r\n")

        body.append(f"--{boundary}--\r\n".encode("utf-8"))
        payload_bytes = b"".join(body)

        req_up = urllib.request.Request(
            "https://check.axes4.com/api/upload",
            data=payload_bytes,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Origin": "https://check.axes4.com",
                "Referer": f"https://check.axes4.com/{language}",
                "User-Agent": "ADA-PDF-Remediator/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req_up, timeout=timeout) as resp:
            raw_output = resp.read().decode("utf-8")
            report = json.loads(raw_output)
            return {"success": True, "report": report}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        return {"success": False, "error": f"axesCheck HTTP {e.code}: {err_body[:300]}"}
    except Exception as e:
        return {"success": False, "error": f"Upload/Audit failed on axesCheck: {e}"}


if __name__ == "__main__":
    from pathlib import Path

    target = sys.argv[1] if len(sys.argv) > 1 else "samples/physics/physics.pdf"
    print(f"Running axesCheck (check.axes4.com) audit on: {target}...")
    res = audit_pdf_axescheck(target)
    print(json.dumps(res, indent=2))
