"""Authoritative per-call state.

Why this exists rather than just using global_data: the platform echoes
global_data as a per-TURN snapshot. Two mutating tool calls in the same turn
both read that snapshot, so the second's write clobbers the first. Holding the
order here makes concurrent mutations compose. global_data is still mirrored
outward so the prompt can speak the running total.

This is only authoritative with a single worker — see the Dockerfile.
"""

import threading
import time

_lock = threading.Lock()
_orders = {}          # call_id -> {"items": [...], "ts": epoch, "placed": bool}
_recent = {}          # call_id -> {"sig": str, "ts": epoch, "response": str}

TTL = 4 * 3600        # drop state from calls that ended without cleanup
DEDUP_WINDOW = 2.0    # seconds; shorter than any human re-order
MAX_CALLS = 1000


def _prune(now):
    for cid in [c for c, v in _orders.items() if now - v.get("ts", 0) > TTL]:
        _orders.pop(cid, None)
        _recent.pop(cid, None)
    if len(_orders) > MAX_CALLS:
        oldest = sorted(_orders.items(), key=lambda kv: kv[1].get("ts", 0))
        for cid, _ in oldest[: len(_orders) - MAX_CALLS]:
            _orders.pop(cid, None)
            _recent.pop(cid, None)


def call_id_of(raw_data):
    """Best-effort call identity; falls back to a shared bucket for local tests."""
    if isinstance(raw_data, dict):
        for key in ("call_id", "callId"):
            if raw_data.get(key):
                return str(raw_data[key])
        call = raw_data.get("call")
        if isinstance(call, dict) and call.get("call_id"):
            return str(call["call_id"])
    return "local-test"


def get(call_id):
    with _lock:
        _prune(time.time())
        return dict(_orders.get(call_id) or {"items": [], "placed": False})


def add_item(call_id, item, qty, options, unit_price=None):
    """Add or accumulate. Identical item+options merge into one line with a
    quantity, so 'another latte' reads as '2 x Latte' rather than two lines."""
    with _lock:
        now = time.time()
        _prune(now)
        s = _orders.setdefault(call_id, {"items": [], "ts": now, "placed": False})
        if s.get("placed"):
            # A placed order is closed. Start a fresh one rather than silently
            # mutating something the caller was already given a number for.
            s = _orders[call_id] = {"items": [], "ts": now, "placed": False}
        for line in s["items"]:
            if line["sku"] == item["sku"] and line.get("options", "") == (options or ""):
                line["qty"] = line.get("qty", 1) + qty
                break
        else:
            s["items"].append({
                "sku": item["sku"], "name": item["name"],
                    "price": unit_price if unit_price is not None else item["price"],
                "qty": qty, "options": options or "",
            })
        s["ts"] = now
        return dict(s)


def place(call_id):
    """Close the order. Idempotent: re-asking returns the same number and does
    not re-place, so a repeated 'that's it' cannot double-submit."""
    with _lock:
        now = time.time()
        s = _orders.get(call_id)
        if not s or not s.get("items"):
            return None, False
        if s.get("placed"):
            return dict(s), False
        s["placed"] = True
        s["order_number"] = _order_number(call_id)
        s["ts"] = now
        return dict(s), True


import zlib


def _order_number(call_id):
    """Stable per call, different between calls, unchanged by a restart.

    A process counter gave every fresh container the same first number (8919),
    so two demos handed out identical tickets. hash() is salted per process and
    was no better; crc32 of the call id is neither.
    """
    return str(1000 + (zlib.crc32(str(call_id).encode()) % 9000))


def mutate(call_id, fn):
    """Apply fn to this call's order under the lock. Returns the new state."""
    with _lock:
        now = time.time()
        _prune(now)
        state = _orders.setdefault(call_id, {"items": [], "ts": now, "placed": False})
        fn(state)
        state["ts"] = now
        return dict(state)


def duplicate_response(call_id, signature):
    """The model sometimes fires one tool twice in ~1s for a single utterance.
    Replaying the first response keeps those from double-adding."""
    with _lock:
        seen = _recent.get(call_id)
        if seen and seen["sig"] == signature and time.time() - seen["ts"] < DEDUP_WINDOW:
            return seen["response"]
    return None


def remember(call_id, signature, response):
    with _lock:
        _recent[call_id] = {"sig": signature, "ts": time.time(), "response": response}


def snapshot(call_id):
    """The order as the UI should see it."""
    s = get(call_id)
    items = s.get("items", [])
    return {
        "items": items,
        "total": total(s),
        "count": sum(i.get("qty", 1) for i in items),
        "placed": s.get("placed", False),
        "order_number": s.get("order_number"),
        "customer": s.get("customer"),
        "summary": summary(s),
    }


def event(call_id, tool, spoken, refused=False, detail=None, ms=None):
    """Payload pushed to the browser via FunctionResult.swml_user_event.

    Polling told the UI what changed a second late and never said why. This
    carries the tool that ran, what it said, whether the code overruled the
    model, and the resulting order -- so the page can show the decision, not
    just the outcome.
    """
    record(call_id, tool, spoken, refused, detail, ms)
    return {
        "type": "tool",
        "call_id": call_id,
        "tool": tool,
        "spoken": spoken,
        "refused": bool(refused),
        "ms": ms,
        "detail": detail or {},
        "order": snapshot(call_id),
        "ts": time.time(),
    }


def record(call_id, tool, spoken, refused=False, args=None, ms=None):
    """Persist what the agent was asked and what it answered.

    The platform logs 'function_executed_successfully' for a refusal exactly as
    for a success, with no arguments and no reply text. Reviewing a call after
    the fact was therefore guesswork: two add_to_order lines and a cookie on the
    ticket looked like two successes, when the first had been refused and the
    caller had to insist.
    """
    entry = {
        "ts": time.time(),
        "tool": tool,
        "args": {k: str(v)[:60] for k, v in (args or {}).items()},
        "refused": bool(refused),
        "ms": ms,
        "spoken": (spoken or "")[:300],
    }
    with _lock:
        s = _orders.setdefault(call_id, {"items": [], "ts": time.time(), "placed": False})
        s.setdefault("history", []).append(entry)
        del s["history"][:-40]
        s["ts"] = entry["ts"]
    # Also to stdout, so the container log alone is enough to review a call.
    print(
        "TOOL %s %s %s %sms -> %s"
        % (call_id, tool, "REFUSED" if refused else "ok",
           "?" if ms is None else int(ms), (spoken or "")[:160]),
        flush=True,
    )
    return entry


def median_ms(call_id):
    """Median handler time for this call, or None before anything has run."""
    times = sorted(h["ms"] for h in get(call_id).get("history", []) if h.get("ms") is not None)
    return round(times[len(times) // 2], 1) if times else None


def history(call_id):
    return list(get(call_id).get("history", []))
ORDERING_WORDS = ("order", "ordered", "wanted", "asked for", "latte", "coffee",
                  "add", "requested", "bought", "purchase")


def anomalies(call_id, summary=""):
    """Detect a call that went wrong, from evidence we already hold.

    A model that answers without calling tools cannot be caught by testing the
    tools -- they all work. But the aftermath is deterministic: a summary that
    describes an order beside a ticket that is empty, a checkout as the only
    tool call, the same refusal repeating. Each of these has actually happened.
    """
    s = get(call_id)
    hist = s.get("history", [])
    items = s.get("items", [])
    text = (summary or s.get("summary_text") or "").lower()
    found = []

    if text and not items and any(w in text for w in ORDERING_WORDS):
        found.append(
            "summary describes an order but the ticket is empty - the agent "
            "probably tracked it in conversation instead of calling add_to_order"
        )

    mutating = [h for h in hist if h["tool"] not in ("get_menu", "review_order")]
    if len(mutating) == 1 and mutating[0]["refused"] and "nothing on the order" in mutating[0]["spoken"].lower():
        found.append("the only action attempted was a checkout on an empty order")

    if hist and not any(h["tool"].startswith(("add", "order", "buy")) for h in hist) and text:
        found.append("a whole call with no add_to_order call")

    # The same refusal repeating means the reply gave the model no way forward.
    seen = {}
    for h in hist:
        if not h["refused"]:
            continue
        k = (h["tool"], h["spoken"][:60])
        seen[k] = seen.get(k, 0) + 1
        if seen[k] == 3:
            found.append(f"{h['tool']} refused identically 3+ times - the reply offers no way to succeed")

    return found


def note_summary(call_id, summary, transcript=None):
    """Keep the post-call summary with the session it belongs to.

    Without a post_prompt the platform records call-state events only, so there
    is nothing to review after a call: no summary, no transcript, no way to see
    what the caller actually asked for.
    """
    with _lock:
        s = _orders.setdefault(call_id, {"items": [], "ts": time.time(), "placed": False})
        s["summary_text"] = summary
        if transcript:
            s["transcript"] = transcript[-60:]
        s["ts"] = time.time()
def note_name(call_id, name):
    """Remember the caller's name so the ticket can be signed."""
    if not name or not str(name).strip():
        return
    with _lock:
        s = _orders.setdefault(call_id, {"items": [], "ts": time.time(), "placed": False})
        s["customer"] = str(name).strip()[:40]
        s["ts"] = time.time()


def note_tool(call_id, tool, item_sku=None):
    """Record the agent's last action so the UI can highlight it live."""
    with _lock:
        s = _orders.setdefault(call_id, {"items": [], "ts": time.time(), "placed": False})
        s["last_tool"] = tool
        s["last_sku"] = item_sku
        s["last_tool_ts"] = time.time()
        s["ts"] = time.time()


IDLE_WINDOW = 900  # seconds an order stays "current" for the web panel


def latest():
    """Most recent active order, ACROSS ALL CALLS.

    Only safe when a single caller is expected. The web UI must not use this:
    with two concurrent calls it shows one caller another caller's ticket. Scope
    to a call_id instead -- see snapshot(call_id).
    """
    with _lock:
        now = time.time()
        live = {c: v for c, v in _orders.items() if now - v.get("ts", 0) < IDLE_WINDOW}
        if not live:
            return None
        cid = max(live, key=lambda c: (not live[c].get("placed", False), live[c].get("ts", 0)))
        return dict(live[cid])


def total(state):
    return round(sum(i["price"] * i.get("qty", 1) for i in state.get("items", [])), 2)


def summary(state):
    items = state.get("items", [])
    if not items:
        return "nothing yet"
    parts = []
    for i in items:
        qty = i.get("qty", 1)
        opts = f" ({i['options']})" if i.get("options") else ""
        parts.append(f"{qty} {i['name']}{opts}" if qty > 1 else f"{i['name']}{opts}")
    return ", ".join(parts)
