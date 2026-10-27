"""Strict data boundary for synthetic chat signals; never a clinical risk score."""
import json
from pathlib import Path
from django.conf import settings
from assistant.client import ProviderError

POLICY = json.loads(Path(__file__).with_name("alert_policy.demo.json").read_text())
POLICY_VERSION = POLICY["policy_version"]
TIME_LABELS = {"current": "В сообщении относится к настоящему", "past": "Упоминание прошлого",
               "unclear": "Время неясно"}


def mode_output():
    mode = settings.ASSISTANT_ALERTING_MODE
    return {"alerting_mode": mode, "demo_detection_enabled": mode == "demo",
            "automatic_detection_enabled": False}  # Legacy field always describes clinical detection.


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def parse_analysis(raw, text):
    """Only known IDs and exact current-message evidence cross into persisted state."""
    try:
        data = json.loads(raw, object_pairs_hook=unique_object)
        if not isinstance(data, dict) or set(data) != {"reply", "analysis"}:
            raise ValueError()
        reply, analysis = data["reply"], data["analysis"]
        if not isinstance(reply, str) or not reply.strip() or len(reply) > POLICY["limits"]["reply_characters"]:
            raise ValueError()
        if not isinstance(analysis, dict) or set(analysis) != {"status", "signals"}:
            raise ValueError()
        status, signals = analysis["status"], analysis["signals"]
        if status not in ("matched", "no_match", "uncertain") or not isinstance(signals, list):
            raise ValueError()
        if len(signals) > POLICY["limits"]["max_signals"] or (status == "no_match") != (not signals):
            raise ValueError()
        result, seen = [], set()
        for signal in signals:
            if not isinstance(signal, dict) or set(signal) != {"category", "quote", "time"}:
                raise ValueError()
            category, quote, when = signal["category"], signal["quote"], signal["time"]
            if not all(isinstance(x, str) for x in (category, quote, when)):
                raise ValueError()
            if category not in POLICY["categories"] or category in seen or when not in TIME_LABELS:
                raise ValueError()
            if category == "ambiguous" and status != "uncertain":
                raise ValueError()
            if not quote.strip() or len(quote) > POLICY["limits"]["quote_characters"] or quote not in text:
                raise ValueError()
            seen.add(category)
            rule = POLICY["categories"][category]
            result.append({"category": category, "quote": quote, "time": when,
                "label": rule["label"], "time_label": TIME_LABELS[when],
                "source_ref": POLICY["source"]["id"] + " · " + rule["section"]})
        return reply.strip(), status, result
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ProviderError("invalid_response") from None
