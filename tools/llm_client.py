"""LLM response parsing utilities.

The LLMClient and UsageTracker classes have been replaced by AgentSDKClient
(see tools/agent_sdk_client.py). This module retains the JSON parsing
functions used across the codebase.
"""

import json
import re

# Precompiled regex for JSON extraction
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)

# Lenient decoder that allows control characters (raw newlines, tabs) inside
# JSON strings — LLMs frequently produce these instead of proper \n escapes.
_LENIENT_DECODER = json.JSONDecoder(strict=False)


def _try_loads(text: str) -> dict:
    """Try parsing JSON, first strictly then leniently."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fallback: allow unescaped control characters in strings
    try:
        return _LENIENT_DECODER.decode(text)
    except json.JSONDecodeError:
        pass
    raise json.JSONDecodeError("", text, 0)


def _ensure_dict(result) -> dict:
    """Ensure the parsed JSON result is a dict.

    LLMs sometimes return a JSON array when a dict is expected.
    If we get a list, use the first dict element; otherwise wrap it.
    """
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                return item
        return {"items": result}
    return {"value": result}


def parse_json_response(text: str) -> dict:
    """Extract and parse JSON from LLM response text.

    Handles cases where JSON is wrapped in markdown code fences,
    and tolerates unescaped newlines inside JSON string values
    (a common LLM output quirk).

    Always returns a dict — lists are normalized via _ensure_dict.
    """
    text = text.strip()

    # Try direct parse first
    try:
        return _ensure_dict(_try_loads(text))
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code fences
    match = _JSON_FENCE_RE.search(text)
    if match:
        try:
            return _ensure_dict(_try_loads(match.group(1).strip()))
        except json.JSONDecodeError:
            pass

    # Try finding JSON object or array boundaries
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            try:
                return _ensure_dict(_try_loads(text[start:end + 1]))
            except json.JSONDecodeError:
                continue

    raise ValueError(f"Failed to parse JSON from LLM response: {text[:200]}...")
