import os
import json
import hashlib
import hmac
import time
from datetime import date
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import requests

# ── Config ──
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
ANAS_SLACK_ID = os.environ["ANAS_SLACK_ID"]

app = FastAPI()


def verify_slack_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    """Verify that the request actually came from Slack."""
    if abs(time.time() - int(timestamp)) > 300:
        return False
    basestring = f"v0:{timestamp}:{request_body.decode()}"
    computed = "v0=" + hmac.HMAC(
        SLACK_SIGNING_SECRET.encode(), basestring.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


def send_eod_message(items: list[dict]) -> dict:
    """
    Send an EOD update DM to Anas.

    Each item dict:
      - text: str
      - type: "info" or "decision"
      - options: list[str] (button labels for decisions)
                 defaults to ["Yes, go ahead", "No"]
    """
    today_str = date.today().strftime("%A, %B %d %Y")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📋 Stephan's EOD update"}
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_{today_str}_"}]
        },
        {"type": "divider"},
    ]

    for i, item in enumerate(items):
        item_type = item.get("type", "info")
        text = item["text"]

        # Section text
        if item_type == "decision":
            section_text = f"🟡 *Needs your call*\n{text}"
        else:
            section_text = text

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": section_text}
        })

        # Buttons
        if item_type == "decision":
            options = item.get("options", ["Yes, go ahead", "No"])
            buttons = []
            for opt in options:
                style = None
                if opt.lower().startswith("yes") or opt.lower() in ("go ahead", "lock it in", "confirm"):
                    style = "primary"
                elif opt.lower().startswith("no") or opt.lower() in ("reject", "pass"):
                    style = "danger"
                btn = {
                    "type": "button",
                    "text": {"type": "plain_text", "text": opt},
                    "action_id": f"eod_{i}_{opt.lower().replace(' ', '_')[:20]}",
                    "value": json.dumps({"idx": i, "choice": opt, "text": text[:200]}),
                }
                if style:
                    btn["style"] = style
                buttons.append(btn)
            # Always add Discuss
            buttons.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "🚩 Discuss tomorrow"},
                "action_id": f"eod_{i}_discuss",
                "value": json.dumps({"idx": i, "choice": "Discuss tomorrow", "text": text[:200]}),
            })
            blocks.append({"type": "actions", "elements": buttons})
        else:
            blocks.append({
                "type": "actions",
                "elements": [{
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🚩 Discuss tomorrow"},
                    "action_id": f"eod_{i}_discuss",
                    "value": json.dumps({"idx": i, "choice": "Discuss tomorrow", "text": text[:200]}),
                }]
            })

        blocks.append({"type": "divider"})

    # Open DM channel with Anas
    conv = requests.post(
        "https://slack.com/api/conversations.open",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={"users": ANAS_SLACK_ID},
    ).json()

    if not conv.get("ok"):
        return conv

    channel_id = conv["channel"]["id"]

    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={"channel": channel_id, "blocks": blocks, "text": "Stephan's EOD update"},
    )
    return resp.json()


# ── Endpoints ──

@app.post("/send")
async def send_update(request: Request):
    """
    POST /send with JSON body:
    {
      "items": [
        {"text": "Finished the Woodhull cutlist", "type": "info"},
        {"text": "ConEd wants Thursday site visit. Confirm?", "type": "decision"},
        {"text": "Lock in Bactolac at $14.20?", "type": "decision", "options": ["Lock it in", "Wait"]}
      ]
    }
    """
    body = await request.json()
    items = body.get("items", [])
    if not items:
        return JSONResponse({"error": "No items provided"}, status_code=400)
    try:
        result = send_eod_message(items)
        print(f"Slack API response: {result}")
        if result.get("ok"):
            return {"status": "sent", "channel": result.get("channel"), "ts": result.get("ts")}
        else:
            return JSONResponse({"error": result.get("error")}, status_code=500)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/slack/interactions")
async def handle_interaction(request: Request):
    """Handle button clicks from Anas."""
    body = await request.body()

    # Verify Slack signature
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if not verify_slack_signature(body, timestamp, signature):
        return Response(status_code=403)

    form_data = (await request.form())["payload"]
    payload = json.loads(form_data)

    user_name = payload["user"]["username"]
    action = payload["actions"][0]
    value = json.loads(action["value"])
    choice = value["choice"]

    # Replace the clicked button block with Anas's response
    blocks = payload["message"]["blocks"]
    action_block_id = action["block_id"]

    new_blocks = []
    for block in blocks:
        if block.get("block_id") == action_block_id:
            if "yes" in choice.lower() or "go" in choice.lower() or "lock" in choice.lower() or "confirm" in choice.lower():
                emoji = "✅"
            elif "discuss" in choice.lower():
                emoji = "🚩"
            else:
                emoji = "❌"
            new_blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"{emoji} *@{user_name}*: _{choice}_"}]
            })
        else:
            new_blocks.append(block)

    requests.post(
        "https://slack.com/api/chat.update",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={
            "channel": payload["channel"]["id"],
            "ts": payload["message"]["ts"],
            "blocks": new_blocks,
            "text": "Stephan's EOD update (responded)",
        },
    )

    return Response(status_code=200)


@app.get("/health")
async def health():
    return {"status": "ok"}
