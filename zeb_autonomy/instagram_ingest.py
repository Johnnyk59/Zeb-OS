"""Instagram perception for Zeb — ingestion pipeline (credentials-gated).

Directive #7 asks for Zeb to "manage his own Instagram" and see reels the user
sends to his account. Here is the honest engineering reality, stated plainly so
nobody is misled:

  There is NO API that lets a script silently watch the DMs/reels sent to an
  Instagram account. Receiving that content requires a Meta *Business* account,
  a Meta App, the ``instagram_manage_messages`` permission, and Meta's app
  review — and Meta gates reel/DM webhooks heavily. Until those real
  credentials exist and Meta approves the app, this pipeline receives nothing.

So this module is the *real pipeline* with an inert front door: it defines how
an incoming item is normalised, saved, and fed into Zeb's shared context — but
``is_configured()`` returns False and ``poll()`` is a no-op until the Meta
credentials below are set. It does not fake inbound content. When Zeb (or the
user) connects a real Meta app, the same pipeline starts carrying real reels.

Configuration (all via env / Zeb config, none hardwired):
  IG_APP_ID, IG_APP_SECRET, IG_ACCESS_TOKEN, IG_BUSINESS_ACCOUNT_ID,
  IG_VERIFY_TOKEN (and optionally IG_GRAPH_VERSION)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

_REQUIRED_ENV = ("IG_APP_ID", "IG_APP_SECRET", "IG_ACCESS_TOKEN", "IG_BUSINESS_ACCOUNT_ID")


def _zeb_home() -> Path:
    try:
        import zeb_constants

        return Path(zeb_constants.get_zeb_home())
    except Exception:
        return Path.home() / ".zeb"


def _inbox_path() -> Path:
    return _zeb_home() / "instagram" / "inbox.json"


def is_configured() -> bool:
    """True only when every required Meta credential is present."""
    return all(os.environ.get(k, "").strip() for k in _REQUIRED_ENV)


def verify_webhook_token(token: str) -> bool:
    """Validate Meta's webhook verification token."""
    expected = os.environ.get("IG_VERIFY_TOKEN", "").strip()
    return bool(expected and token and hmac.compare_digest(expected, str(token)))


def verify_signature(raw_body: bytes, signature: str | None) -> bool:
    """Validate Meta's ``X-Hub-Signature-256`` header."""
    secret = os.environ.get("IG_APP_SECRET", "").strip()
    supplied = str(signature or "").strip()
    if not secret or not supplied.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied.removeprefix("sha256="), digest)


def status() -> dict:
    """Human-readable status for the dashboard / diagnostics."""
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k, "").strip()]
    return {
        "configured": not missing,
        "missing_credentials": missing,
        "note": (
            "Connected — pipeline live."
            if not missing
            else "Inert until a Meta Business app + access token are connected. "
            "Instagram does not expose DM/reel content without Meta app review."
        ),
        "inbox_count": len(_read_inbox()),
    }


def _read_inbox() -> list[dict]:
    try:
        data = json.loads(_inbox_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def ingest_item(item: dict) -> dict:
    """Normalise one inbound item (a reel/DM), persist it, and let Zeb perceive it.

    This is the pipeline's real core. It runs whenever a genuine Meta webhook or
    ``poll()`` hands it an item — it is not called with fabricated data. It saves
    the item and mirrors a note into Zeb's shared context so any session sees it.
    """
    norm = {
        "type": item.get("type", "reel"),
        "from": item.get("from", ""),
        "url": item.get("url", ""),
        "caption": item.get("caption", ""),
        "media_id": item.get("media_id", ""),
        "received_at": time.time(),
    }
    try:
        path = _inbox_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        inbox = _read_inbox()
        inbox.append(norm)
        inbox = inbox[-500:]
        path.write_text(json.dumps(inbox, indent=2), encoding="utf-8")
    except Exception:
        pass
    # Fold into the one shared context so it becomes part of Zeb's awareness.
    try:
        from zeb_chat.stores import SharedContextStore

        summary = f"[instagram] {norm['type']} from {norm['from'] or 'someone'}: {norm['caption'][:200]}".strip()
        SharedContextStore().append("user", summary, session="instagram", provider="instagram")
        try:
            from tui_gateway.server import broadcast_shared_context

            broadcast_shared_context("user", summary, sid="instagram", provider="instagram")
        except Exception:
            pass
    except Exception:
        pass
    return norm


def ingest_webhook(payload: dict) -> list[dict]:
    """Normalize Instagram messaging events into the shared perception log."""
    ingested: list[dict] = []
    entries = payload.get("entry", []) if isinstance(payload, dict) else []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for event in entry.get("messaging", []) or []:
            if not isinstance(event, dict):
                continue
            message = event.get("message") or {}
            if not isinstance(message, dict):
                message = {}
            sender = (event.get("sender") or {}).get("id", "")
            attachments = message.get("attachments") or [{}]
            for attachment in attachments:
                attachment = attachment if isinstance(attachment, dict) else {}
                media = attachment.get("payload") or {}
                media = media if isinstance(media, dict) else {}
                item = ingest_item(
                    {
                        "type": attachment.get("type") or "message",
                        "from": sender,
                        "url": media.get("url") or "",
                        "caption": message.get("text") or "",
                        "media_id": media.get("id") or "",
                    }
                )
                item["raw"] = event
                ingested.append(item)
    return ingested


def send_reply(recipient_id: str, text: str) -> dict:
    """Send a text reply through Meta's Instagram Messaging API."""
    recipient = str(recipient_id or "").strip()
    message = str(text or "").strip()
    if not recipient or not message:
        return {"ok": False, "error": "recipient_id and text are required"}
    if not is_configured():
        return {"ok": False, "error": "Instagram credentials are not configured"}

    version = os.environ.get("IG_GRAPH_VERSION", "v20.0").strip() or "v20.0"
    endpoint = (
        f"https://graph.facebook.com/{version}/"
        f"{os.environ['IG_BUSINESS_ACCOUNT_ID'].strip()}/messages"
    )
    payload = json.dumps(
        {
            "recipient": {"id": recipient},
            "message": {"text": message[:2000]},
            "access_token": os.environ["IG_ACCESS_TOKEN"].strip(),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw) if raw else {}
        return {"ok": True, "response": data}
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")[:1000]
        except Exception:
            detail = str(exc)
        return {"ok": False, "error": detail or str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def poll() -> list[dict]:
    """Pull new items from the Instagram Graph API.

    No-op (returns ``[]``) until credentials are configured. When they are, this
    is where the real Graph API call goes; the returned items flow through
    :func:`ingest_item`. Left unimplemented rather than faked so it never
    pretends to have seen content it did not.
    """
    if not is_configured():
        return []
    # Instagram Messaging is webhook-driven; the webhook route calls
    # ``ingest_webhook`` because there is no reliable inbox poll endpoint for
    # shared reels.
    return []
