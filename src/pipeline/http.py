"""Helpers for API Gateway HTTP API events (payload format 2.0)."""
import base64
import json


class BadRequest(Exception):
    """A client error. Handlers turn it into a 400 response."""


def json_response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def parse_json_body(event):
    """The request body as a dict. An empty body counts as {}."""
    raw = event.get("body") or ""
    try:
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        body = json.loads(raw) if raw.strip() else {}
    except (ValueError, UnicodeDecodeError) as err:
        raise BadRequest("Request body must be valid JSON") from err
    if not isinstance(body, dict):
        raise BadRequest("Request body must be a JSON object")
    return body


def path_param(event, name):
    return (event.get("pathParameters") or {}).get(name)


def query_param(event, name):
    return (event.get("queryStringParameters") or {}).get(name)


def base_url(event):
    return f"https://{event['requestContext']['domainName']}"
