# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through
[GitHub Security Advisories](https://github.com/krishaygarg/ada_pdf_remediation/security/advisories/new)
rather than opening a public issue.

Include the affected version, a description of the impact, and the smallest
input that reproduces the problem. We aim to acknowledge reports within five
working days.

## Scope

This project parses untrusted PDF documents and, when deployed with the
optional web interface, accepts file uploads over the network. The areas most
likely to matter are:

- Parsing malformed or hostile PDF documents
- Resource exhaustion from crafted documents, such as deeply nested structures
  or decompression bombs
- Path handling in the upload and download endpoints
- Command construction where the project shells out to Poppler or Tesseract

## Handling of uploaded documents

Documents may contain personal or confidential information, so the project
treats transmission as something the operator opts into rather than a default:

- Remediation and the local auditor run entirely offline.
- `check-compliance --remote` uploads the document to `check.axes4.com`, a third
  party service. It refuses to run without the explicit `--consent-upload` flag.
- The web interface writes uploads to a scratch directory on the server. Anyone
  deploying it publicly should configure a retention policy and serve it over
  HTTPS.

## Supported versions

The most recent release on `main` receives fixes. There is no long term support
branch.
