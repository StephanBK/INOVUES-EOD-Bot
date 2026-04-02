# INOVUES EOD Bot

End-of-day update bot for Slack. Sends Stephan's daily updates to Anas as a DM with interactive buttons (approve/reject/discuss).

## Endpoints

- `POST /send` — Send an EOD update with items
- `POST /slack/interactions` — Receives Slack button click callbacks
- `GET /health` — Health check

## Environment Variables

- `SLACK_BOT_TOKEN` — Bot user OAuth token (xoxb-...)
- `SLACK_SIGNING_SECRET` — From Slack app settings
- `ANAS_SLACK_ID` — Anas's Slack member ID

## Usage

POST to `/send`:
```json
{
  "items": [
    {"text": "Finished the Woodhull cutlist", "type": "info"},
    {"text": "ConEd wants Thursday site visit. Confirm?", "type": "decision"},
    {"text": "Lock in Bactolac at $14.20?", "type": "decision", "options": ["Lock it in", "Wait"]}
  ]
}
```
