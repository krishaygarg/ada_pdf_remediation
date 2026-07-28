#!/usr/bin/env python3
"""
axesCheck (check.axes4.com) PDF Accessibility Checker API Client & MCP Module.
Solves ALTCHA proof-of-work challenges in <1ms and posts PDFs to check.axes4.com/api/upload.
"""

import os
import sys
import json
import base64
import hashlib
import subprocess


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
                "signature": signature
            }
            return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
            
    return ""


def audit_pdf_axescheck(pdf_path: str, language: str = "en") -> dict:
    """
    Submits a PDF file to check.axes4.com API and returns the full accessibility audit report.
    """
    if not os.path.exists(pdf_path):
        return {"success": False, "error": f"File not found: {pdf_path}"}

    # 1. Fetch ALTCHA challenge via curl
    try:
        cmd_challenge = ["curl", "-s", "--http1.1", "https://check.axes4.com/api/challenge"]
        res_ch = subprocess.run(cmd_challenge, capture_output=True, text=True, check=True)
        challenge_data = json.loads(res_ch.stdout)
    except Exception as e:
        return {"success": False, "error": f"Failed to fetch challenge: {e}"}

    # 2. Solve challenge
    altcha_payload = solve_altcha_challenge(challenge_data)
    if not altcha_payload:
        return {"success": False, "error": "Failed to solve ALTCHA challenge."}

    # 3. Upload PDF file via curl with token, file, language fields
    try:
        cmd_upload = [
            "curl", "-s", "--http1.1",
            "-X", "POST",
            "-H", "Origin: https://check.axes4.com",
            "-H", f"Referer: https://check.axes4.com/{language}",
            "-F", f"file=@{pdf_path}",
            "-F", f"token={altcha_payload}",
            "-F", f"language={language}",
            "https://check.axes4.com/api/upload"
        ]
        res_up = subprocess.run(cmd_upload, capture_output=True, text=True, check=True)
        raw_output = res_up.stdout
        try:
            report = json.loads(raw_output)
            return {"success": True, "report": report}
        except Exception:
            return {"success": False, "error": f"axesCheck non-JSON output: {raw_output[:300]}"}
    except Exception as e:
        return {"success": False, "error": f"Upload/Audit failed on axesCheck: {e}"}




if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "samples/physics/physics.pdf"
    print(f"Running axesCheck (check.axes4.com) audit on: {target}...")
    res = audit_pdf_axescheck(target)
    print(json.dumps(res, indent=2))



