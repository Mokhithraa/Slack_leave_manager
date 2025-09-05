import os
from datetime import datetime, date
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request, jsonify

# Environment variables (set your actual tokens and IDs)
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "xoxb-xxxxxx") #enter ur token here
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "ebxxxxxxxxxxxxxxxxxxxxx") #enter the signing secret here
MANAGER_USER_ID = os.environ.get("MANAGER_USER_ID", "U0xxxxxxxxx") #enter the manager ID here
HR_CHANNEL_ID = os.environ.get("HR_CHANNEL_ID", "U0xxxxxxxxx")  # enter the HR ID or HR channel ID here

app = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# Mock in-memory data store for demo
USER_LEAVE_BALANCES = {
    "U0xxxxxxxxx": 10, #enter the user's ID here
    MANAGER_USER_ID: 15,
}
USER_DISCUSSION_STATE = {}  # user_id: bool indicating discussion state

LEAVE_REASONS = [
    {"text": {"type": "plain_text", "text": "Vacation"}, "value": "vacation"},
    {"text": {"type": "plain_text", "text": "Sick Leave"}, "value": "sick"},
    {"text": {"type": "plain_text", "text": "Personal"}, "value": "personal"},
    {"text": {"type": "plain_text", "text": "Other"}, "value": "other"},
]


@app.command("/leave_app")
def open_leave_modal(ack, body, client, logger):
    user_id = body["user_id"]
    remaining_leave = USER_LEAVE_BALANCES.get(user_id, 0)
    ack()

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*You have {remaining_leave} leave days remaining.*",
            },
        },
        {"type": "divider"},
        {
            "type": "input",
            "block_id": "reason_block",
            "element": {
                "type": "static_select",
                "action_id": "reason_action",
                "placeholder": {"type": "plain_text", "text": "Select a reason"},
                "options": LEAVE_REASONS,
            },
            "label": {"type": "plain_text", "text": "Reason for leave"},
        },
        {
            "type": "input",
            "block_id": "start_date_block",
            "element": {
                "type": "datepicker",
                "action_id": "start_date_action",
                "placeholder": {"type": "plain_text", "text": "Select a start date"},
            },
            "label": {"type": "plain_text", "text": "Start date"},
        },
        {
            "type": "input",
            "block_id": "end_date_block",
            "element": {
                "type": "datepicker",
                "action_id": "end_date_action",
                "placeholder": {"type": "plain_text", "text": "Select an end date"},
            },
            "label": {"type": "plain_text", "text": "End date"},
        },
        {
            "type": "input",
            "block_id": "proof_block",
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "proof_action",
                "multiline": True,
                "placeholder": {
                    "type": "plain_text",
                    "text": "Provide proof details or upload files in chat (optional)",
                },
            },
            "label": {"type": "plain_text", "text": "Proof details (optional)"},
        },
    ]

    try:
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "leave_request_modal",
                "title": {"type": "plain_text", "text": "Leave Request"},
                "submit": {"type": "plain_text", "text": "Submit"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": blocks,
            },
        )
    except Exception as e:
        logger.error(f"Error opening leave modal: {e}")


@app.view("leave_request_modal")
def handle_leave_submission(ack, body, client, view, logger):
    user_id = body["user"]["id"]
    values = view["state"]["values"]

    reason = None
    try:
        reason_block = values.get("reason_block", {})
        reason_action = reason_block.get("reason_action", {})
        selected_option = reason_action.get("selected_option")
        if selected_option:
            reason = selected_option.get("text", {}).get("text")
    except Exception:
        reason = None

    if not reason:
        ack(response_action="errors", errors={"reason_block": "Please select a reason."})
        return

    start_date = values.get("start_date_block", {}).get("start_date_action", {}).get("selected_date")
    end_date = values.get("end_date_block", {}).get("end_date_action", {}).get("selected_date")

    errors = {}
    if not start_date:
        errors["start_date_block"] = "Please select a start date."
    if not end_date:
        errors["end_date_block"] = "Please select an end date."

    if errors:
        ack(response_action="errors", errors=errors)
        return

    # Safely extract proof details with None check to avoid attribute errors
    proof_details = ""
    proof_block = values.get("proof_block", {})
    proof_action = proof_block.get("proof_action")
    if proof_action:
        value = proof_action.get("value")
        if value is not None:
            proof_details = value.strip()

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    except Exception:
        ack(response_action="errors", errors={"start_date_block": "Invalid start or end date."})
        return

    today = date.today()
    if reason == "Sick Leave":
        if start_dt > today:
            ack(
                response_action="errors",
                errors={"start_date_block": "Sick leave start date cannot be in the future."},
            )
            return
        # Proof is optional - no error for missing proof. it can be asked in DM personally

    if end_dt < start_dt:
        ack(
            response_action="errors",
            errors={"end_date_block": "End date cannot be before start date."},
        )
        return

    requested_days = (end_dt - start_dt).days + 1
    remaining_leave = USER_LEAVE_BALANCES.get(user_id, 0)

    ack()  # Acknowledge after validation

    client.chat_postMessage(
        channel=user_id,
        text=f"Your leave request for *{requested_days}* days has been applied successfully! The manager will review it shortly.",
    )

    proof_note = (
        f"Proof details submitted.\n*Proof Details:* {proof_details}"
        if proof_details
        else "No proof details submitted."
    )

    message = (
        f"<@{user_id}> has requested leave:\n"
        f"*Reason:* {reason}\n"
        f"*Start Date:* {start_date}\n"
        f"*End Date:* {end_date}\n"
        f"*Requested Days:* {requested_days}\n"
        f"*Remaining Leave:* {remaining_leave}\n"
        f"{proof_note}"
    )

    try:
        dm = client.conversations_open(users=MANAGER_USER_ID)
        channel_id = dm["channel"]["id"]
        client.chat_postMessage(
            channel=channel_id,
            text="New leave request pending approval",
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": message}},
                {
                    "type": "actions",
                    "block_id": "approval_buttons",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Approve"},
                            "style": "primary",
                            "value": f"{user_id}|approved|{requested_days}",
                            "action_id": "approve_button",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Decline"},
                            "style": "danger",
                            "value": f"{user_id}|declined|{requested_days}",
                            "action_id": "decline_button",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Discuss"},
                            "style": "primary",
                            "value": f"{user_id}|discuss|{requested_days}",
                            "action_id": "discuss_button",
                        },
                    ],
                },
            ],
        )
        logger = app.logger
        logger.info("Manager notified with 3 options.")
    except Exception as e:
        app.logger.error(f"Failed to notify manager: {e}")


@app.action("approve_button")
@app.action("decline_button")
def handle_final_decision(ack, body, client, logger):
    ack()
    action_value = body["actions"][0]["value"]
    user_id, decision, requested_days = action_value.split("|")
    manager_id = body["user"]["id"]
    decision_text = "approved" if decision == "approved" else "declined"

    client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text=f"Leave request has been *{decision_text}* by <@{manager_id}>.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Leave request has been *{decision_text}* by <@{manager_id}>.",
                },
            }
        ],
    )

    client.chat_postMessage(
        channel=user_id,
        text=f"Your leave request for *{requested_days}* days was *{decision_text}* by <@{manager_id}>.",
    )

    client.chat_postMessage(
        channel=HR_CHANNEL_ID,
        text=f"Leave request from <@{user_id}> for *{requested_days}* days was *{decision_text}* by <@{manager_id}>.",
    )

    if decision == "approved":
        current_balance = USER_LEAVE_BALANCES.get(user_id, 0)
        USER_LEAVE_BALANCES[user_id] = max(0, current_balance - int(requested_days))


@app.action("discuss_button")
def handle_discuss_action(ack, body, client, logger):
    ack()
    user_id, _, requested_days = body["actions"][0]["value"].split("|")
    manager_id = body["user"]["id"]

    try:
        blocks = body["message"]["blocks"]
        for block in blocks:
            if block.get("block_id") == "approval_buttons":
                for elem in block["elements"]:
                    elem["disabled"] = True
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            text="Leave request is under discussion",
            blocks=blocks,
        )
    except Exception as e:
        logger.error(f"Failed to disable buttons after discuss: {e}")

    USER_DISCUSSION_STATE[user_id] = True

    try:
        client.chat_postMessage(
            channel=user_id,
            text=(
                f"<@{manager_id}> wants to discuss your leave request for *{requested_days}* days.\n"
                "Please schedule and complete the huddle or meeting.\n"
                "Once done, you can *Re-request* your leave."
            ),
            blocks=[
                {
                    "type": "actions",
                    "block_id": "rerequest_block",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Re-request Leave"},
                            "style": "primary",
                            "value": f"{user_id}|{requested_days}",
                            "action_id": "rerequest_button",
                        }
                    ],
                }
            ],
        )
    except Exception as e:
        logger.error(f"Failed to send discussion DM to user: {e}")


@app.action("rerequest_button")
def handle_rerequest_button(ack, body, client, logger):
    ack()
    user_id, requested_days = body["actions"][0]["value"].split("|")
    manager_id = MANAGER_USER_ID

    if not USER_DISCUSSION_STATE.get(user_id, False):
        client.chat_postMessage(
            channel=user_id,
            text="You need to discuss the leave request with your manager before re-requesting.",
        )
        return

    try:
        dm = client.conversations_open(users=manager_id)
        channel_id = dm["channel"]["id"]
        message = (
            f"<@{user_id}> has re-requested leave after discussion for *{requested_days}* days.\n"
            "_Note: The user has already discussed this leave request._"
        )
        client.chat_postMessage(
            channel=channel_id,
            text="Leave re-request pending approval",
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": message}},
                {
                    "type": "actions",
                    "block_id": "final_approval_buttons",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Approve"},
                            "style": "primary",
                            "value": f"{user_id}|approved|{requested_days}",
                            "action_id": "approve_button",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Decline"},
                            "style": "danger",
                            "value": f"{user_id}|declined|{requested_days}",
                            "action_id": "decline_button",
                        },
                    ],
                },
            ],
        )
        logger.info(f"Manager notified of re-request from user {user_id}.")
        USER_DISCUSSION_STATE[user_id] = False
    except Exception as e:
        logger.error(f"Failed to notify manager for re-request: {e}")


@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    if request.headers.get("content-type") == "application/json":
        data = request.get_json()
        if data.get("type") == "url_verification":
            return jsonify({"challenge": data["challenge"]})
    return handler.handle(request)


@flask_app.route("/", methods=["GET"])
def home():
    return "Slack Leave App is running!", 200


if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=8000)
