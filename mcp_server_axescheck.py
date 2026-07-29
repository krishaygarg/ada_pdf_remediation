#!/usr/bin/env python3
"""
MCP (Model Context Protocol) Server for axesCheck (check.axes4.com) PDF Accessibility Checker.
Enables AI models to run official PDF/UA & WCAG compliance audits via stdio JSON-RPC.
"""

import json
import sys


def respond(response_obj):
    sys.stdout.write(json.dumps(response_obj) + "\n")
    sys.stdout.flush()


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except Exception:
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            respond(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "axescheck-mcp-server", "version": "1.0.0"},
                    },
                }
            )
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            respond(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": "audit_pdf_axescheck",
                                "description": "Submits a PDF document to axesCheck (check.axes4.com) for official PDF/UA (ISO 14289-1) and WCAG 2.1 A/AA machine-verifiable accessibility compliance evaluation according to the Matterhorn Protocol.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "pdf_path": {
                                            "type": "string",
                                            "description": "Absolute path to the target PDF file to audit for accessibility compliance.",
                                        }
                                    },
                                    "required": ["pdf_path"],
                                },
                            }
                        ]
                    },
                }
            )
        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})
            if tool_name == "audit_pdf_axescheck":
                pdf_path = args.get("pdf_path", "")
                import importlib

                import remediator.axescheck

                importlib.reload(remediator.axescheck)
                result = remediator.axescheck.audit_pdf_axescheck(pdf_path)
                respond(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
                        },
                    }
                )
            else:
                respond(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                    }
                )
        else:
            if req_id is not None:
                respond(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"Method not found: {method}"},
                    }
                )


if __name__ == "__main__":
    main()
