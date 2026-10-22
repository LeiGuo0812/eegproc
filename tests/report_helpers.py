import json
import re


def read_report(document):
    """Read the audit record embedded in a standalone HTML report."""
    match = re.search(r'<script id="run-record" type="application/json">(.*?)</script>', document, re.S)
    assert match, "Missing machine-readable run record"
    return json.loads(match.group(1))
