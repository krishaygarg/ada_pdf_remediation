#!/usr/bin/env python3
"""
ADA PDF Remediator Web Application & REST API Server.
"""

import os
import uuid
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

from remediator.config import LOCAL_TMP
from remediator.pipeline import remediate_single_pdf
from remediator.compliance import run_compliance_check
from remediator.axescheck import audit_pdf_axescheck

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

app = Flask(__name__, static_folder=WEB_DIR, static_url_path="")
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max limit

TASKS_DIR = os.path.join(LOCAL_TMP, "tasks")
os.makedirs(TASKS_DIR, exist_ok=True)


@app.route("/")
def index():
    """Serves the main Web UI interface."""
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/health")
def health():
    """Health check endpoint for deployment monitoring."""
    return jsonify({"status": "healthy", "service": "ADA PDF Remediator API"})


@app.route("/api/remediate", methods=["POST"])
def remediate_api():
    """
    POST /api/remediate
    Accepts a PDF file upload, remediates it to PDF/UA-1 & WCAG standards, and runs compliance checks.
    """
    if "pdf" not in request.files:
        return jsonify({"error": "No PDF file provided in request"}), 400

    file = request.files["pdf"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "File must be a PDF document"}), 400

    task_id = str(uuid.uuid4())
    task_folder = os.path.join(TASKS_DIR, task_id)
    os.makedirs(task_folder, exist_ok=True)

    filename = secure_filename(file.filename)
    input_path = os.path.join(task_folder, filename)
    output_path = os.path.join(task_folder, f"remediated_{filename}")

    file.save(input_path)

    try:
        # Run core remediation pipeline
        remediate_single_pdf(input_path, output_path)

        # Run compliance auditor
        is_compliant = run_compliance_check(output_path, verbose=False)

        return jsonify({
            "status": "success",
            "task_id": task_id,
            "filename": filename,
            "output_filename": f"remediated_{filename}",
            "compliant": is_compliant
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download/<task_id>", methods=["GET"])
def download_api(task_id):
    """
    GET /api/download/<task_id>
    Serves the remediated accessible PDF file.
    """
    # Sanitize task_id (UUID format check)
    clean_task_id = os.path.basename(task_id)
    task_folder = os.path.join(TASKS_DIR, clean_task_id)
    
    if not os.path.exists(task_folder):
        return jsonify({"error": "Task session not found"}), 404

    files = [f for f in os.listdir(task_folder) if f.startswith("remediated_")]
    if not files:
        return jsonify({"error": "Remediated file not found"}), 404

    output_path = os.path.join(task_folder, files[0])
    return send_file(output_path, as_attachment=True, download_name=files[0])

@app.route("/api/axescheck", methods=["POST"])
def axescheck_api():
    """
    POST /api/axescheck
    Runs check.axes4.com audit on uploaded PDF.
    """
    file = request.files.get("pdf") or request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"error": "No PDF file provided"}), 400

    task_id = str(uuid.uuid4())
    task_folder = os.path.join(TASKS_DIR, task_id)
    os.makedirs(task_folder, exist_ok=True)
    input_path = os.path.join(task_folder, secure_filename(file.filename))
    file.save(input_path)

    res = audit_pdf_axescheck(input_path)
    return jsonify(res)


@app.route("/<path:path>")
def static_proxy(path):
    """Serves static assets from web/ or falls back to index.html."""
    if os.path.exists(os.path.join(WEB_DIR, path)):
        return send_from_directory(WEB_DIR, path)
    return send_from_directory(WEB_DIR, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
