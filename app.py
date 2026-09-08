"""Coffee, pastries and a live order ticket on 5th and Main
Generated from the cinebot pattern.
"""
import os
import time
import threading
from signalwire import AgentBase, AgentServer, FunctionResult
from fastapi.responses import JSONResponse
from signalwire.rest import RestClient
import catalog
import state
class CoffeeShopAgent(AgentBase):
    def __init__(self):
        super().__init__(
            name="coffee-shop",
            route="/agent",
            host="0.0.0.0",
            port=int(os.getenv("PORT", "3000")),
            signing_key=os.getenv("SIGNALWIRE_SIGNING_KEY") or None,
        )
        self.set_post_prompt("Summarise the call in two sentences: what the caller ordered, anything you could not do, and how it ended.")
        # If the AI session ends with the call still up, nothing hangs it up
        # and the caller sits on an open line. On the SDK's production
        # checklist, and the game demo has had it for a while -- this one was
        # simply missing.
        self.add_post_ai_verb("hangup", {})

        self.prompt_add_section("Role", body="Coffee, pastries and a live order ticket on 5th and Main")
        self.prompt_add_section("Rules", body="Use your tools before stating facts. Keep replies short and spoken-friendly.")
        self.prompt_add_section("Conversation", body="Open by greeting them and asking whether they already know what they would like or would rather hear what is available. Do not read the menu unless they ask for it or seem unsure. Ask one question at a time and wait for the answer. Always deal with what the caller just asked for before asking anything of your own, and never ask the same question twice in a row. You only need their name to finish the order, so ask for it when they say that is everything -- not at the start.")
        self.prompt_add_section("Tools are the only way to act", body="Your memory of the conversation is NOT the order. Nothing exists until the matching tool has run and returned. Call the tool FIRST, then say what it told you. Never confirm an item, a price, a total or an order number that did not come back from a tool in this turn. If the caller mentions three items, that is three tool calls before you confirm anything.")
        self.prompt_add_section("Never invent a value", body="Every argument you pass to a tool must be something the caller actually said. If a tool needs something you have not been told, ask for it and wait for the answer -- never guess a name, a quantity, a size or a spelling, and never carry one over from an earlier caller. Do not finalise, ring up or close out anything until the caller has said they are finished.")
        self.prompt_add_section("Using your tools", body="Do not announce that you are about to look something up, check, or fetch anything: call the tool and say the answer it returned. 'Let me get the menu' makes the caller wait for nothing. This is about not narrating -- it is never a reason to answer without calling the tool.")

    @AgentBase.tool(
        name="get_name",
        description="Record the caller's first name for the ticket. Use as soon as the caller gives a name, and to ask for one before finishing.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "the caller's first name"},
            },
            "required": ["name"],
        },
    )
    def swaig_get_name(self, args, raw_data):
        """Record the caller's first name for the ticket. Use as soon as the caller gives a name, and to ask for one before finishing. (generated: name behaviour)."""
        _t0 = time.perf_counter()
        call_id = state.call_id_of(raw_data)
        args = args or {}
        state.note_tool(call_id, "get_name")
        # Read the order BEFORE recording, so we can tell a first-time name
        # from a repeat and an empty order from a finished one.
        before = state.get(call_id) or {}
        had_name = (before.get("customer") or "").strip()
        has_items = bool(before.get("items"))
        state.note_name(call_id, args.get("name"))
        given_name = (args.get("name") or "").strip()
        if not given_name:
            _r = FunctionResult("Sorry, I did not catch the name. What is it?")  # refusal
            _r.swml_user_event(state.event(call_id, "get_name", _r.response, refused=True, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
            return _r
        # A recorded call shows this firing twice, seven seconds apart, and
        # both times it ended "What can I get you?" -- to a caller who had
        # already ordered two items and said that was everything. The reply
        # has to fit where in the order we actually are.
        if had_name and had_name.lower() == given_name.lower():
            spoken = f"Still {given_name} on the ticket."
        elif has_items:
            spoken = (f"Thanks {given_name}, that is on the ticket. Shall I "
                      f"ring it up?")
        else:
            spoken = (f"Thanks {given_name}, I have got that on the ticket. "
                      f"What can I get you?")
        _r = FunctionResult(spoken)
        _r.swml_user_event(state.event(call_id, "get_name", _r.response, refused=False, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
        return _r

    @AgentBase.tool(
        name="get_menu",
        description="List what is on the board with prices. Use when the caller asks what is available, or sounds unsure what they want.",
        parameters={"type": "object", "properties": {}},
    )
    def get_menu(self, args, raw_data):
        """List what is on the board with prices. Use when the caller asks what is available, or sounds unsure what they want. (generated: catalog behaviour)."""
        _t0 = time.perf_counter()
        call_id = state.call_id_of(raw_data)
        args = args or {}
        state.note_tool(call_id, "get_menu")
        # Speak a short list; put the full catalog in global_data so the
        # model can answer detail questions without reading everything aloud.
        opt_key, opt_values = catalog.priced_option()
        note = ""
        if opt_key and any(catalog.price_row(i) for i in catalog.CATALOG):
            priced = [i for i in catalog.CATALOG if catalog.price_row(i)]
            spread = catalog.price_row(priced[0]) if priced else []
            note = (
                f" Drinks are priced by {opt_key}: a {priced[0]['name']} is "
                + ", ".join(f"{v} at ${p:.2f}" for v, p in spread) + "."
            )
        result = FunctionResult(
            f"We have {catalog.menu_summary()}.{note} What can I get you?"
        )
        result.update_global_data({
            "menu": [f"{i['name']}: {catalog.spoken_prices(i)}" for i in catalog.CATALOG],
            "menu_size": len(catalog.CATALOG),
        })
        result.swml_user_event(state.event(call_id, "get_menu", result.response, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
        return result

    @AgentBase.tool(
        name="add_to_order",
        description="Add an item. Drinks are priced by size, so pass size for drinks; pass quantity for more than one. Use every time the caller names something they want, once per item.",
        parameters={
            "type": "object",
            "properties": {
                "drink": {
                    "type": "string",
                    "description": "item name from the menu",
                    "enum": ["Drip Coffee", "Latte", "Cappuccino", "Cold Brew", "Chai Latte", "Blueberry Muffin", "Almond Croissant", "Cinnamon Roll", "Cat Paw Cookie", "Water"],
                },
                "size": {
                    "type": "string",
                    "description": "small, medium or large (drinks only)",
                    "enum": ["small", "medium", "large"],
                },
                "quantity": {"type": "string", "description": "how many, e.g. 2"},
            },
            "required": ["drink"],
        },
    )
    def add_to_order(self, args, raw_data):
        """Add an item. Drinks are priced by size, so pass size for drinks; pass quantity for more than one. Use every time the caller names something they want, once per item. (generated: add behaviour)."""
        _t0 = time.perf_counter()
        call_id = state.call_id_of(raw_data)
        args = args or {}
        state.note_tool(call_id, "add_to_order")
        raw_item = args.get("drink")
        item, confidence = catalog.find_item(raw_item)

        # Something we do not stock but get asked for constantly. A written
        # answer beats fuzzy string distance, which used to offer a Latte to
        # somebody who asked for water.
        if confidence == "off_menu":
            lack, instead = catalog.off_menu(raw_item)
            if instead is not None and catalog.is_donation(instead):
                _r = FunctionResult(  # refusal
                    f"We do not have {lack}, but the cookies and the water "
                    f"jug both go to {catalog.DONATION_CAUSE}. Would you like "
                    f"to donate? {catalog.donation_choices()}."
                )
            elif instead is not None:
                _r = FunctionResult(  # refusal
                    f"Sorry, we do not do {lack}. The nearest thing we have "
                    f"is our {instead['name']} at "
                    f"{catalog.spoken_prices(instead)}. Would you like that?"
                )
            else:
                _r = FunctionResult(  # refusal
                    f"Sorry, we do not do {lack} at all -- we are just coffee "
                    f"and pastries. We have {catalog.menu_summary()}. What can "
                    f"I get you?"
                )
            _r.swml_user_event(state.event(call_id, "add_to_order", _r.response, refused=True, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
            return _r

        # Water is free, so there is nothing to add to the order. What we ask
        # for instead is a donation, and that is a separate tool with a fixed
        # set of amounts -- never an open ended "how much?".
        if catalog.is_donation(item):
            _r = FunctionResult(
                f"The water is free, help yourself. If you would like to "
                f"chip in for {catalog.DONATION_CAUSE}, we take "
                f"{catalog.donation_choices()} -- no pressure either way."
            )
            _r.swml_user_event(state.event(call_id, "add_to_order", _r.response, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
            return _r

        # Ambiguous or unmatched: ask rather than guess. Silently turning
        # "coffee" into one specific drink is how a demo loses trust.
        if item is None:
            if confidence == "ambiguous":
                names = " or ".join(c["name"] for c in catalog.matches_for(raw_item)[:3])
                _r = FunctionResult(f"Did you mean {names}?")  # refusal
                _r.swml_user_event(state.event(call_id, "add_to_order", _r.response, refused=True, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
                return _r
            # Not on the menu: name the closest thing rather than reciting the
            # whole board, and ask instead of assuming.
            close = catalog.nearest(raw_item)
            if close:
                alt = close[0]
                also = f", or the {close[1]['name']}" if len(close) > 1 else ""
                _r = FunctionResult(  # refusal
                    f"Sorry, we do not do {raw_item}. The closest is our "
                    f"{alt['name']} at {catalog.spoken_prices(alt)}{also}. "
                    f"Would you like that instead?"
                )
                _r.swml_user_event(state.event(call_id, "add_to_order", _r.response, refused=True, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
                return _r
            _r = FunctionResult(  # refusal
                f"Sorry, we do not do {raw_item}. We have {catalog.menu_summary()}. "
                f"What can I get you?"
            )
            _r.swml_user_event(state.event(call_id, "add_to_order", _r.response, refused=True, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
            return _r
        if confidence == 'fuzzy':
            _r = FunctionResult(  # refusal
                f"Just to check - did you want the {item['name']}?"
            )
            _r.swml_user_event(state.event(call_id, "add_to_order", _r.response, refused=True, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
            return _r

        given_opt = args.get("size")
        ok, chosen, allowed, surcharge = catalog.validate_option("size", given_opt, item)
        ignored_opt = bool(given_opt) and not allowed
        if not ok:
            prices = catalog.OPTIONS.get("size", {})
            allowed_text = ", ".join(
                "%s $%.2f" % (a, item["price"] + prices.get(a, 0.0))
                for a in allowed
            )
            _r = FunctionResult(  # refusal
                f"We do not have {given_opt} for size. "
                f"We have {allowed_text}. Which would you like?"
            )
            _r.swml_user_event(state.event(call_id, "add_to_order", _r.response, refused=True, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
            return _r
        if not chosen and allowed:
            prices = catalog.OPTIONS.get("size", {})
            choice_text = ", ".join(
                "%s $%.2f" % (a, item["price"] + prices.get(a, 0.0))
                for a in allowed
            )
            _r = FunctionResult(  # refusal
                "What size for the %s? We have %s."
                % (item["name"], choice_text)
            )
            _r.swml_user_event(state.event(call_id, "add_to_order", _r.response, refused=True, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
            return _r
        qty = catalog.parse_quantity(args.get("quantity"), catalog.parse_quantity(raw_item))

        # The platform can retry one utterance; a genuine repeat arrives as a
        # quantity, so an identical call inside the window is a retry.
        signature = f"add:{item['sku']}:{chosen}:{qty}"
        replay = state.duplicate_response(call_id, signature)
        if replay:
            _r = FunctionResult(replay)
            _r.swml_user_event(state.event(call_id, "add_to_order", _r.response, refused=False, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
            return _r

        state.note_tool(call_id, 'add_to_order', item['sku'])
        unit = round(item['price'] + surcharge, 2)
        new_state = state.add_item(call_id, item, qty, chosen, unit)
        running = state.total(new_state)
        opts = f" {chosen}" if chosen else ""
        line = f"{qty} {item['name']}{opts}" if qty > 1 else f"{item['name']}{opts}"
        priced = f" at ${unit:.2f}" if surcharge else ""
        aside = " - those come one size" if ignored_opt else ""
        spoken = (
            f"Got it, {line}{priced}{aside}. "
            f"That is {state.summary(new_state)}, ${running:.2f} so far. Anything else?"
        )
        state.remember(call_id, signature, spoken)
        result = FunctionResult(spoken)
        result.update_global_data({
            "order_summary": state.summary(new_state),
            "order_total": f"{running:.2f}",
            "item_count": sum(i.get("qty", 1) for i in new_state["items"]),
        })
        result.swml_user_event(state.event(call_id, "add_to_order", result.response, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
        return result

    @AgentBase.tool(
        name="remove_from_order",
        description="Remove an item. Use when the caller changes their mind or asks to take something off.",
        parameters={
            "type": "object",
            "properties": {
                "drink": {
                    "type": "string",
                    "description": "item name to remove",
                    "enum": ["Drip Coffee", "Latte", "Cappuccino", "Cold Brew", "Chai Latte", "Blueberry Muffin", "Almond Croissant", "Cinnamon Roll", "Cat Paw Cookie", "Water"],
                },
            },
            "required": ["drink"],
        },
    )
    def remove_from_order(self, args, raw_data):
        """Remove an item. Use when the caller changes their mind or asks to take something off. (generated: remove behaviour)."""
        _t0 = time.perf_counter()
        call_id = state.call_id_of(raw_data)
        args = args or {}
        state.note_tool(call_id, "remove_from_order")
        raw_item = args.get("drink")
        item, _ = catalog.find_item(raw_item)
        removed = {}

        def apply(s):
            if item is None:
                s["items"].clear()
                return
            for i in range(len(s["items"]) - 1, -1, -1):
                if s["items"][i]["sku"] == item["sku"]:
                    line = s["items"][i]
                    if line.get("qty", 1) > 1:
                        line["qty"] -= 1
                    else:
                        s["items"].pop(i)
                    removed["item"] = line
                    break

        new_state = state.mutate(call_id, apply)
        running = state.total(new_state)
        if item is None:
            spoken = "I cleared the order. Shall we start again?"
        elif not removed:
            spoken = (
                f"I do not see a {item['name']} on the order. "
                f"You have {state.summary(new_state)}."
            )
        else:
            spoken = (
                f"Removed one {item['name']}. "
                f"You now have {state.summary(new_state)}, ${running:.2f}."
            )
        result = FunctionResult(spoken)
        result.update_global_data({
            "order_summary": state.summary(new_state),
            "order_total": f"{running:.2f}",
        })
        result.swml_user_event(state.event(call_id, "remove_from_order", result.response, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
        return result

    @AgentBase.tool(
        name="donate",
        description=(
            "Add a donation for cat food and litter to the order. Use when "
            "the caller agrees to donate, or asks for water and then names an "
            "amount. Only $10, $20 and $30 are accepted -- if they say any "
            "other amount, this will tell you so; offer the three and let "
            "them pick. Never invent an amount they did not say, and never "
            "add a donation they did not agree to."
        ),
        parameters={
            "type": "object",
            "properties": {
                "amount": {
                    "type": "string",
                    "description": "how much they said: 10, 20 or 30 dollars",
                    "enum": ["10", "20", "30"],
                },
            },
            "required": ["amount"],
        },
    )
    def donate(self, args, raw_data):
        """Add a fixed-tier donation for cat food and litter."""
        _t0 = time.perf_counter()
        call_id = state.call_id_of(raw_data)
        args = args or {}
        state.note_tool(call_id, "donate")
        tier, why = catalog.donation_tier(args.get("amount"))
        if tier is None:
            said = str(args.get("amount") or "").strip()
            spoken = (
                f"We take {catalog.donation_choices()} for "
                f"{catalog.DONATION_CAUSE}."
            )
            if why == "not a tier" and said:
                spoken = (
                    f"Sorry, we cannot take ${said} -- the tins are set up "
                    f"for {catalog.donation_choices()}. Which would you like?"
                )
            _r = FunctionResult(spoken)  # refusal
            _r.swml_user_event(state.event(call_id, "donate", _r.response, refused=True, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
            return _r

        water = next(i for i in catalog.CATALOG
                     if i["sku"] == catalog.DONATION_SKU)
        # unit_price carries the tier, so three different donations do not
        # merge into one line at the wrong amount.
        new_state = state.add_item(call_id, water, 1,
                                   f"donation ${tier:.0f}", unit_price=tier)
        running = state.total(new_state)
        result = FunctionResult(
            f"Thank you -- ${tier:.2f} for {catalog.DONATION_CAUSE}, and the "
            f"water is on us. That is ${running:.2f} altogether."
        )
        result.update_global_data({
            "order_summary": state.summary(new_state),
            "order_total": f"{running:.2f}",
        })
        result.swml_user_event(state.event(call_id, "donate", result.response, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
        return result

    @AgentBase.tool(
        name="review_order",
        description="Read back the order. Use when the caller asks what they have so far, or to confirm before finishing.",
        parameters={"type": "object", "properties": {}},
    )
    def review_order(self, args, raw_data):
        """Read back the order. Use when the caller asks what they have so far, or to confirm before finishing. (generated: status behaviour)."""
        _t0 = time.perf_counter()
        call_id = state.call_id_of(raw_data)
        args = args or {}
        state.note_tool(call_id, "review_order")
        current = state.get(call_id)
        if not current.get("items"):
            _r = FunctionResult("Nothing on the order yet. What can I get you?")  # refusal
            _r.swml_user_event(state.event(call_id, "review_order", _r.response, refused=True, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
            return _r
        running = state.total(current)
        _r = FunctionResult(
            f"You have {state.summary(current)}, ${running:.2f} total."
        )
        _r.swml_user_event(state.event(call_id, "review_order", _r.response, refused=False, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
        return _r

    @AgentBase.tool(
        name="place_order",
        description="Finalise and give the pickup time. Use only once the caller has said that is everything.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "the caller's first name"},
            },
            "required": ["name"],
        },
    )
    def place_order(self, args, raw_data):
        """Finalise and give the pickup time. Use only once the caller has said that is everything. (generated: checkout behaviour)."""
        _t0 = time.perf_counter()
        call_id = state.call_id_of(raw_data)
        args = args or {}
        state.note_tool(call_id, "place_order")
        state.note_name(call_id, args.get("name"))
        # place() is idempotent: a repeated "that's it" returns the same
        # number instead of submitting twice.
        placed, is_new = state.place(call_id)
        if placed is None:
            _r = FunctionResult(  # refusal
                "There is nothing on the order yet. What can I get started for you?"
            )
            _r.swml_user_event(state.event(call_id, "place_order", _r.response, refused=True, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
            return _r

        who = (args.get("name") or "").strip()
        running = state.total(placed)
        number = placed["order_number"]
        if not is_new:
            _r = FunctionResult(  # refusal
                f"That order is already in - number {number}, ${running:.2f}."
            )
            _r.swml_user_event(state.event(call_id, "place_order", _r.response, refused=True, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
            return _r

        ready = 5 + 2 * sum(i.get("qty", 1) for i in placed["items"])
        greeting = f"Thanks {who}. " if who else ""
        spoken = (
            f"{greeting}That is {state.summary(placed)}, ${running:.2f} total. "
            f"Your order number is {number}, ready in about {ready} minutes."
        )
        result = FunctionResult(spoken)
        result.update_global_data({
            "order_number": number,
            "order_total": f"{running:.2f}",
            "order_placed": True,
        })
        result.swml_user_event(state.event(call_id, "place_order", result.response, detail=dict(args), ms=round((time.perf_counter() - _t0) * 1000, 1)))
        return result

    def on_summary(self, summary, raw_data=None):
        """Post-call summary from the platform, kept with the session."""
        raw = raw_data or {}
        call_id = state.call_id_of(raw)
        if isinstance(summary, dict):
            text = summary.get("summary") or summary.get("text") or ""
        else:
            text = str(summary or "")
        convo = raw.get("call_log") or raw.get("conversation") or []
        state.note_summary(call_id, text, convo)
        # Audit the finished call against itself. A model that answered
        # without calling tools leaves a summary describing an order beside
        # an empty ticket - detectable with no model in the loop.
        for problem in state.anomalies(call_id, text):
            print(f"CALL-ANOMALY {call_id} {problem}", flush=True)

# Shown in the UI so the page describes this specific demo, and so the
# capability strip lists exactly the tools the agent was given.
_SHOP = {"name": "coffee-shop", "tagline": "Coffee, pastries and a live order ticket on 5th and Main"}
_TOOLS = {
    "get_name": "Record the caller's first name for the ticket.",
    "get_menu": "List what is on the board with prices.",
    "add_to_order": "Add an item. Drinks are priced by size, so pass size for drinks; pass quantity for more than one.",
    "remove_from_order": "Remove an item.",
    "review_order": "Read back the order.",
    "place_order": "Finalise and give the pickup time.",
    # A hand-maintained mirror of the real tool list, used only to draw the
    # panel. donate was added to the agent and not here, so the browser never
    # lit up when a donation was taken.
    "donate": "Add a $10, $20 or $30 donation for cat food and litter."
}


# --- web endpoints ------------------------------------------------------
# The browser needs three things: the catalog to render, the live order to
# mirror, and a guest token + address to dial. Token minting follows the
# corpus: register the agent as a SWML webhook resource, then issue a guest
# token scoped to that address.

_handler = {"id": None, "address_id": None, "address": None, "error": None}
_handler_lock = threading.Lock()


def _rest_client():
    space = os.getenv("SIGNALWIRE_SPACE_NAME") or os.getenv("SIGNALWIRE_SPACE", "")
    project = os.getenv("SIGNALWIRE_PROJECT_ID", "")
    token = os.getenv("SIGNALWIRE_TOKEN") or os.getenv("SIGNALWIRE_API_TOKEN", "")
    if not (space and project and token):
        return None
    host = space if "." in space else f"{space}.signalwire.com"
    return RestClient(project=project, token=token, host=host)


def _public_url():
    """Publicly reachable agent URL, with basic-auth userinfo.

    The agent protects its own endpoints with basic auth, so a bare
    https://host/agent registered as the webhook gets a 401 when the
    platform fetches SWML. Credentials go in the userinfo, the same way
    the SDK builds its own SWAIG web_hook_url.
    """
    base = os.getenv("SWML_PROXY_URL_BASE", "").rstrip("/")
    if not base:
        return ""
    user = os.getenv("SWML_BASIC_AUTH_USER", "")
    password = os.getenv("SWML_BASIC_AUTH_PASSWORD", "")
    if user and password:
        from urllib.parse import quote, urlsplit, urlunsplit

        parts = urlsplit(base)
        netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{parts.netloc}"
        base = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    return f"{base}/agent"


def _register_handler():
    """Register this agent as a SWML webhook so the browser can dial it."""
    client = _rest_client()
    if client is None:
        _handler["error"] = "SIGNALWIRE_SPACE_NAME / _PROJECT_ID / _TOKEN not set"
        return
    url = _public_url()
    if not url:
        _handler["error"] = "SWML_PROXY_URL_BASE not set — the browser needs a publicly reachable agent URL"
        return
    try:
        name = "CoffeeShopAgent"
        existing = None
        for h in client.fabric.swml_webhooks.list().get("data", []):
            nested = h.get("swml_webhook") or {}
            if nested.get("name") == name or h.get("display_name") == name:
                existing = h
                break
        if existing:
            handler_id = existing["id"]
            client.fabric.swml_webhooks.update(handler_id, name=name, primary_request_url=url)
        else:
            created = client.fabric.swml_webhooks.create(name=name, primary_request_url=url)
            handler_id = created["id"]
        addresses = client.fabric.swml_webhooks.list_addresses(handler_id).get("data", [])
        if not addresses:
            _handler["error"] = "handler registered but has no address yet"
            return
        addr = addresses[0]
        _handler.update({"id": handler_id, "address_id": addr["id"],
                         "address": addr.get("channels", {}).get("audio") or addr.get("name"),
                         "error": None})
    except Exception as exc:  # surfaced to the browser, not just the log
        _handler["error"] = f"{type(exc).__name__}: {exc}"


def add_web_routes(server):
    @server.app.middleware("http")
    async def _cache_policy(request, call_next):
        """Correct caching, so a deployed fix is the fix you see.

        The SDK serves static files with no Cache-Control, under names that
        never change, so a browser reuses the previous build's CSS and JS
        indefinitely -- a fixed layout still looks broken and no request
        even reaches the server. HTML must always revalidate; the asset
        URLs carry a content hash, so those can be cached hard.
        """
        response = await call_next(request)
        path = request.url.path
        if path.endswith((".css", ".js")) and request.url.query.startswith("v="):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path.endswith((".html", "/")) or path == "":
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response

    @server.app.get("/api/catalog")
    def api_catalog():
        return catalog.CATALOG

    @server.app.get("/api/state")
    def api_state(call_id: str = ""):
        """Everything the agent can see, scoped to one call.

        call_id is required to see an order. Without it the catalog, options
        and tools are returned but the order is empty -- returning whatever
        order was touched most recently would show one caller another
        caller's ticket."""
        current = state.get(call_id) if call_id else {}
        items = current.get("items", []) if call_id else []
        tools = []
        for name, meta in sorted(_TOOLS.items()):
            tools.append({
                "name": name, "description": meta,
                "active": current.get("last_tool") == name
                          and (time.time() - current.get("last_tool_ts", 0)) < 6,
            })
        return {
            "shop": _SHOP,
            "catalog": [
                {**i, "section": i.get("section") or "", "variants": [
                    {"label": v, "price": pr} for v, pr in catalog.price_row(i)
                ]}
                for i in catalog.CATALOG
            ],
            "options": catalog.OPTIONS,
            "tools": tools,
            "order": {
                "items": items,
                "total": state.total(current) if items else 0.0,
                "count": sum(i.get("qty", 1) for i in items),
                "call_id": call_id or None,
                "placed": current.get("placed", False),
                "order_number": current.get("order_number"),
                "last_tool": current.get("last_tool"),
                "last_sku": current.get("last_sku"),
                "customer": current.get("customer"),
                "summary": current.get("summary_text"),
                "transcript": current.get("transcript") or [],
                "history": current.get("history") or [],
                "median_ms": state.median_ms(call_id),
                "anomalies": state.anomalies(call_id) if call_id else [],
            },
        }


    @server.app.get("/get_token")
    def get_token():
        """Guest token plus the address the browser should dial."""
        client = _rest_client()
        if client is None:
            return JSONResponse(
                {"error": "SignalWire credentials not configured "
                          "(SIGNALWIRE_SPACE_NAME / SIGNALWIRE_PROJECT_ID / SIGNALWIRE_TOKEN)"},
                status_code=500)
        if not _handler.get("address_id"):
            with _handler_lock:
                if not _handler.get("address_id"):
                    _register_handler()
        if not _handler.get("address_id"):
            return JSONResponse({"error": _handler.get("error") or "handler not registered"},
                                status_code=500)
        try:
            guest = client.fabric.tokens.create_guest_token(
                allowed_addresses=[_handler["address_id"]],
                expire_at=int(time.time()) + 3600,
            )
            return {"token": guest.get("token", ""), "address": _handler["address"]}
        except Exception as exc:
            return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)

    return server


def build_server() -> AgentServer:
    """Agent plus the static front-end, on one port."""
    server = AgentServer(host="0.0.0.0", port=int(os.getenv("PORT", "3000")))
    # No route override: register() uses the agent's own route, so the
    # SWAIG webhook URLs it generates match where it is actually mounted.
    server.register(CoffeeShopAgent())

    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
    if os.path.isdir(web_dir):
        # Agent routes take priority over static files.
        server.serve_static_files(web_dir)
    add_web_routes(server)
    return server


if __name__ == "__main__":
    build_server().run()
