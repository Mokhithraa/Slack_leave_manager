import os
from datetime import datetime, date, timedelta
from collections import defaultdict
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from slack_sdk.errors import SlackApiError
from sqlalchemy.orm import joinedload
from dateutil.parser import parse
from notion_client import Client as NotionClient
import urllib.parse

# Environment configuration

#From https://api.slack.com: 
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "xoxb-...") #Enter your Bot User OAuth Token
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "...") #Enter your Signing Secret from Basic Information in Slack API
MANAGER_USER_ID = os.environ.get("MANAGER_USER_ID", "...") #Enter the Maanger's ID from your slack workspace
HR_CHANNEL_ID = os.environ.get("HR_CHANNEL_ID", "...") #Enter the HR's ID from your slack workspace

#From Notion API:
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "...") #Enter your Notion secret key
NOTION_TASKS_DB_ID = os.environ.get("NOTION_TASKS_DB_ID", "...") #Enter the Table ID (from the url)

app = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///leaveapp.db'
flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(flask_app)

# Constants and config
LEAVE_TYPES_DATA = [
    {"name": "Casual", "max_days": 6},
    {"name": "Sick", "max_days": 4},
]
MIN_NOTICE = {"Casual": 1}

# Database models
class LeaveType(db.Model):
    __tablename__ = 'leave_type'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    max_days = db.Column(db.Integer, nullable=False)


class UserLeaveBalance(db.Model):
    __tablename__ = 'user_leave_balance'
    user_id = db.Column(db.String(50), primary_key=True)
    leave_type_id = db.Column(db.Integer, db.ForeignKey('leave_type.id'), primary_key=True)
    leave_balance = db.Column(db.Integer, nullable=False)
    leave_type = db.relationship('LeaveType')


class LeaveRequest(db.Model):
    __tablename__ = 'leave_request'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False)
    leave_type_id = db.Column(db.Integer, db.ForeignKey('leave_type.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False)  # "approved", "declined", or "pending"
    leave_type = db.relationship('LeaveType')


USER_DISCUSSION_STATE = {}

# Utility functions
def get_leave_type_options():
    with flask_app.app_context():
        leave_types = LeaveType.query.filter(LeaveType.name.in_(["Casual", "Sick"])).all()
        options = []
        for lt in leave_types:
            options.append({"text": {"type": "plain_text", "text": lt.name}, "value": str(lt.id)})
        return options


def initialize_leave_types_and_user_balances():
    with flask_app.app_context():
        LeaveType.query.filter(~LeaveType.name.in_(['Casual', 'Sick'])).delete(synchronize_session=False)
        db.session.commit()
        for lt_data in LEAVE_TYPES_DATA:
            lt = LeaveType.query.filter_by(name=lt_data["name"]).first()
            if not lt:
                lt = LeaveType(name=lt_data["name"], max_days=lt_data["max_days"])
                db.session.add(lt)
        db.session.commit()


def initialize_user_balances(user_id):
    with flask_app.app_context():
        leave_types = LeaveType.query.filter(LeaveType.name.in_(["Casual", "Sick"])).all()
        for lt in leave_types:
            existing = UserLeaveBalance.query.filter_by(user_id=user_id, leave_type_id=lt.id).first()
            if not existing:
                balance = lt.max_days
                new_balance = UserLeaveBalance(user_id=user_id, leave_type_id=lt.id, leave_balance=balance)
                db.session.add(new_balance)
        db.session.commit()


def calculate_leave_days_excluding_weekends(start_dt, end_dt):
    total_days = (end_dt - start_dt).days + 1
    full_weeks = total_days // 7
    leftover_days = total_days % 7
    weekend_days = full_weeks * 2
    skipped_weekends = []
    for i in range(leftover_days):
        day = start_dt + timedelta(days=full_weeks * 7 + i)
        if day.weekday() == 5 or day.weekday() == 6:
            weekend_days += 1
            skipped_weekends.append(day)
    for i in range(total_days):
        day = start_dt + timedelta(days=i)
        if day.weekday() == 5 or day.weekday() == 6:
            if day not in skipped_weekends:
                skipped_weekends.append(day)
    skipped_weekends.sort()
    leave_days = total_days - weekend_days
    return leave_days, skipped_weekends


def fetch_user_tasks_with_deadlines(notion, tasks_db_id, notion_user_id, leave_start, leave_end):
    filter_ = {
        "and": [
            {
                "property": "Assign",
                "people": {"contains": "26bd872b-594c-81cd-8aa1-0002dc180e8b"}
            },
            {
                "or": [
                    {"property": "Status", "status": {"equals": "Not Started"}},
                    {"property": "Status", "status": {"equals": "In Progress"}}
                ]
            },
            {
                "property": "Due",
                "date": {
                    "on_or_before": leave_end.strftime("%Y-%m-%d"),
                    "on_or_after": leave_start.strftime("%Y-%m-%d")
                }
            }
        ]
    }
    result = notion.databases.query(database_id=tasks_db_id, filter=filter_)
    tasks = []
    project_cache = {}

    for row in result.get("results", []):
        props = row.get("properties", {})
        # Extract task name
        task_name = ""
        if props.get("Task name", {}).get("title", []):
            task_name = props["Task name"]["title"][0].get("text", {}).get("content", "")

        # Extract due date (start only)
        due = props.get("Due", {}).get("date", {}).get("start", "")

        # Extract project relation and fetch project name
        project_relations = props.get("Project", {}).get("relation", [])
        project_name = "Unknown"
        if project_relations:
            project_id = project_relations[0].get("id")
            if project_id in project_cache:
                project_name = project_cache[project_id]
            else:
                project_page = notion.pages.retrieve(project_id)
                title_prop = project_page.get("properties", {})
                # Find first property of type 'title'
                for prop_name, prop_value in title_prop.items():
                    if prop_value.get("type") == "title":
                        title_array = prop_value.get("title", [])
                        if len(title_array) > 0:
                            project_name = "".join([t.get("plain_text", "") for t in title_array])
                        break
                project_cache[project_id] = project_name

        tasks.append({
            "name": task_name,
            "due": due,
            "project": project_name
        })

    # Sort tasks by due date safely using dateutil.parser
    def safe_due(task):
        due_str = task.get('due')
        if not due_str:
            return datetime.max
        try:
            return parse(due_str)
        except Exception:
            return datetime.max

    tasks.sort(key=safe_due)
    return tasks

# Slack command to open leave modal
@app.command("/applyforleave")
def open_leave_modal(ack, body, client, logger):
    user_id = body["user_id"]
    with flask_app.app_context():
        initialize_leave_types_and_user_balances()
        initialize_user_balances(user_id)
        leave_options = get_leave_type_options()
        balances = UserLeaveBalance.query.filter_by(user_id=user_id).options(joinedload(UserLeaveBalance.leave_type)).all()
    ack()
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Your available leave balances:*\n"
                        f"• Casual Leave: {next((b.leave_balance for b in balances if b.leave_type.name=='Casual'), 0)} day(s)\n"
                        f"• Sick Leave: {next((b.leave_balance for b in balances if b.leave_type.name=='Sick'), 0)} day(s)"
            },
        },
        {"type": "divider"},
        {
            "type": "input",
            "block_id": "reason_block",
            "element": {
                "type": "static_select",
                "action_id": "reason_action",
                "placeholder": {"type": "plain_text", "text": "Select a leave type"},
                "options": leave_options,
            },
            "label": {"type": "plain_text", "text": "Leave type"},
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

# Handle modal submission, leave validation, Notion check, Slack messaging
@app.view("leave_request_modal")
def handle_leave_submission(ack, body, client, view, logger):
    user_id = body["user"]["id"]
    values = view["state"]["values"]
    reason_block = values.get("reason_block", {})
    reason_action = reason_block.get("reason_action", {})
    selected_option = reason_action.get("selected_option")
    if selected_option:
        leave_type_id = int(selected_option.get("value"))
    else:
        ack(response_action="errors", errors={"reason_block": "Please select a leave type."})
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
    with flask_app.app_context():
        user_leave_type = LeaveType.query.get(leave_type_id)
        if not user_leave_type or user_leave_type.name not in ["Casual", "Sick"]:
            ack(response_action="errors", errors={"reason_block": "Invalid leave type."})
            return
        user_balance_record = UserLeaveBalance.query.filter_by(user_id=user_id, leave_type_id=leave_type_id).first()
        if not user_balance_record:
            user_balance_record = UserLeaveBalance(user_id=user_id, leave_type_id=leave_type_id, leave_balance=user_leave_type.max_days)
            db.session.add(user_balance_record)
            db.session.commit()
        remaining_leave = user_balance_record.leave_balance
        if user_leave_type.name == "Sick":
            if start_dt > today:
                ack(response_action="errors", errors={"start_date_block": "Sick leave cannot be applied for future dates."})
                return
            if start_dt < today - timedelta(days=14):
                ack(response_action="errors", errors={"start_date_block": "Sick leave must be applied within 14 days of the leave date."})
                return
        else:
            notice_days_required = MIN_NOTICE.get(user_leave_type.name, 0)
            days_notice = (start_dt - today).days
            if days_notice < notice_days_required:
                ack(response_action="errors", errors={"start_date_block":
                    f"{user_leave_type.name} leave must be applied at least {notice_days_required} day(s) in advance. Please select a later start date."})
                return
    if end_dt < start_dt:
        ack(response_action="errors", errors={"end_date_block": "End date cannot be before start date."})
        return
    leave_days, skipped_weekends = calculate_leave_days_excluding_weekends(start_dt, end_dt)
    if leave_days > remaining_leave:
        ack(response_action="errors", errors={
            "start_date_block": f"Insufficient leave balance for {user_leave_type.name}. You have only {remaining_leave} day(s) left.",
            "end_date_block": f"Insufficient leave balance for {user_leave_type.name}. You have only {remaining_leave} day(s) left.",
        })
        return
    ack()  # Respond to Slack before outbound calls
    with flask_app.app_context():
        leave_request = LeaveRequest(
            user_id=user_id, leave_type_id=leave_type_id,
            start_date=start_dt, end_date=end_dt,
            status="pending"
        )
        db.session.add(leave_request)
        db.session.commit()
    skipped_weekends_str = ", ".join(day.strftime("%-d/%-m/%y") for day in skipped_weekends) if skipped_weekends else "none"

    # Notion Integration
    notion_client = NotionClient(auth=NOTION_API_KEY)
    # Slack to Notion user ID mapping: must be maintained manually for real users
    slack_to_notion_user_map = {
        # Example mapping
        "U09DHCLQK8A": "26bd872b-594c-81cd-8aa1-0002dc180e8b",
        # Add your mappings here
    }
    notion_user_id = slack_to_notion_user_map.get(user_id)
    tasks = []
    if notion_user_id:
        tasks = fetch_user_tasks_with_deadlines(notion_client, NOTION_TASKS_DB_ID, notion_user_id, start_dt, end_dt)

    if skipped_weekends_str.lower() != "none":
        confirmation_text = (
            f"Your leave request for *{leave_days} day(s)* of *{user_leave_type.name}* leave "
            f"has been successfully submitted (excluding Saturdays and Sundays: {skipped_weekends_str}).\n"
        )
    else:
        confirmation_text = (
            f"Your leave request for *{leave_days} day(s)* of *{user_leave_type.name}* leave "
            "has been successfully submitted.\n"
        )
    if tasks:
        lines = ["*⚠️ You have the following deadlines during your leave (ordered by due date):*"]
        for t in tasks:
            due_str = t['due'] if t['due'] else "N/A"
            project_str = t['project'] if t['project'] else "Unknown"
            lines.append(f"• {t['name']} (Due: {due_str}) [{project_str}]")
        confirmation_text += "\n".join(lines)
    else:
        confirmation_text += "No project/task deadlines overlap with your leave window."

    client.chat_postMessage(channel=user_id, text=confirmation_text)

    proof_note = f"Proof details submitted:\n*{proof_details}*" if proof_details else "No proof details were provided."
    if tasks:
        tasks_text = "\n".join([f"• {t['name']} (Due: {t['due'] or 'N/A'}) [{t['project'] or 'Unknown'}]" for t in tasks])
    else:
        tasks_text = "No project/task deadlines overlap with the leave dates."

    manager_message = (
        f"Leave Request from <@{user_id}>:\n"
        f"*Type:* {user_leave_type.name}\n"
        f"*Period:* {start_date} to {end_date}\n"
        f"*Total Days (excluding weekends):* {leave_days}\n"
        f"*Remaining {user_leave_type.name} Leave:* {remaining_leave}\n"
        f"{proof_note}\n"
        f"Tasks overlapping with the leave date:\n{tasks_text}"
    )


    try:
        dm = client.conversations_open(users=MANAGER_USER_ID)
        channel_id = dm["channel"]["id"]
        client.chat_postMessage(channel=channel_id, text=manager_message, blocks=[
            {"type": "section", "text": {"type": "mrkdwn", "text": manager_message}},
            {
                "type": "actions",
                "block_id": "approval_buttons",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Approve"}, "style": "primary",
                     "value": f"{user_id}|approved|{leave_days}|{leave_type_id}", "action_id": "approve_button"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Decline"}, "style": "danger",
                     "value": f"{user_id}|declined|{leave_days}|{leave_type_id}", "action_id": "decline_button"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Discuss"}, "style": "primary",
                     "value": f"{user_id}|discuss|{leave_days}|{leave_type_id}", "action_id": "discuss_button"},
                ],
            },
        ])
    except Exception as e:
        app.logger.error(f"Failed to notify manager: {e}")


# /whos_away command
@app.command("/whos_away")
def whos_away_command(ack, body, client, logger):
    ack()
    user_id = body["user_id"]
    try:
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "whos_away_modal",
                "title": {"type": "plain_text", "text": "Who's Away Query"},
                "submit": {"type": "plain_text", "text": "Show"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "period_block",
                        "element": {
                            "type": "static_select",
                            "action_id": "period_select",
                            "placeholder": {"type": "plain_text", "text": "Select period"},
                            "options": [
                                {"text": {"type": "plain_text", "text": "Next 7 days"}, "value": "7days"},
                                {"text": {"type": "plain_text", "text": "Next 30 days"}, "value": "30days"},
                                {"text": {"type": "plain_text", "text": "This month"}, "value": "this_month"},
                            ],
                        },
                        "label": {"type": "plain_text", "text": "Select period"},
                    }
                ],
            },
        )
    except SlackApiError as e:
        logger.error(f"Error opening who's away modal: {e}")

@app.view("whos_away_modal")
def whos_away_modal_submission(ack, body, client, view, logger):
    ack()
    user_id = body["user"]["id"]
    selected_period = view["state"]["values"]["period_block"]["period_select"]["selected_option"]["value"]
    today = date.today()
    if selected_period == "7days":
        start_dt = today
        end_date = today + timedelta(days=6)
        title = "next 7 days"
    elif selected_period == "30days":
        start_dt = today
        end_date = today + timedelta(days=29)
        title = "next 30 days"
    elif selected_period == "this_month":
        start_of_month = today.replace(day=1)
        if today.month == 12:
            end_of_month = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end_of_month = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        start_dt = today if today > start_of_month else start_of_month
        end_date = end_of_month
        title = "this month"
    else:
        client.chat_postMessage(channel=user_id, text="Invalid period selected.")
        return
    with flask_app.app_context():
        approved_leaves = LeaveRequest.query.filter(
            LeaveRequest.status == "approved",
            LeaveRequest.start_date <= end_date,
            LeaveRequest.end_date >= start_dt,
        ).all()
        date_to_users = defaultdict(list)
        for leave in approved_leaves:
            leave_start = max(leave.start_date, start_dt)
            leave_end = min(leave.end_date, end_date)
            delta_days = (leave_end - leave_start).days + 1
            for i in range(delta_days):
                d = leave_start + timedelta(days=i)
                date_to_users[d].append(f"<@{leave.user_id}>")
        msg_lines = [f"Who's Away ({title})"]
        temp_lines = []
        current_day = start_dt
        max_line_length = 0
        while current_day <= end_date:
            day_str = current_day.strftime("%d/%m/%Y")
            weekday_short = current_day.strftime("%a")
            base_line = f"{day_str} - {weekday_short}"
            temp_lines.append((current_day, base_line))
            max_line_length = max(max_line_length, len(base_line))
            current_day += timedelta(days=1)
        for idx, (this_day, base_line) in enumerate(temp_lines):
            users = date_to_users.get(this_day, [])
            user_text = ", ".join(users) if users else "NA"
            padded_line = base_line.ljust(max_line_length)
            msg_lines.append(f"{padded_line} → {user_text}")
            if this_day.weekday() == 6 and this_day != end_date:
                msg_lines.append("-------------------------------")
        message_text = "\n".join(msg_lines)
    try:
        client.chat_postMessage(channel=user_id, text=message_text)
    except SlackApiError as e:
        logger.error(f"Failed to send who's away DM: {e}")

# /leave_balance command
@app.command("/leave_balance")
def leave_balance_command(ack, body, client, logger):
    ack()
    user_id = body["user_id"]
    with flask_app.app_context():
        balances = UserLeaveBalance.query.filter_by(user_id=user_id).join(LeaveType).filter(LeaveType.name.in_(["Casual", "Sick"])).all()
        if not balances:
            text = "No leave balance data found for you."
        else:
            lines = [f"{bal.leave_type.name}: {bal.leave_balance} day(s)" for bal in balances]
            text = "\n".join(lines)
    try:
        client.chat_postMessage(channel=user_id, text=text)
    except SlackApiError as e:
        logger.error(f"Failed to send leave balance DM: {e}")

#change here
@app.action("approve_button")
@app.action("decline_button")
def handle_final_decision(ack, body, client, logger):
    ack()
    action_value = body["actions"][0]["value"]
    
    # Split the button value and get parameters
    # Expect button value format: user_id|decision|requested_days|leave_type_id
    parts = action_value.split("|")
    user_id = parts[0]
    decision = parts[1]
    requested_days = int(parts[2])
    leave_type_id = int(parts[3])
    
    manager_id = body["user"]["id"]
    decision_text = "approved" if decision == "approved" else "declined"

    client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text=f"Leave request has been *{decision_text}* by <@{manager_id}>.",
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn", "text": f"Leave request has been *{decision_text}* by <@{manager_id}>."}}
        ],
    )

    client.chat_postMessage(
        channel=user_id,
        text=(
            f"Your leave request for *{requested_days} day(s)* has been *{decision_text}* by <@{manager_id}>. "
            "Please contact your manager if you have questions."
        ),
    )

    # Fetch overlapping tasks for HR notification
    with flask_app.app_context():
        # Fetch leave request dates for the user and type (last pending or approved)
        leave_request = LeaveRequest.query.filter_by(user_id=user_id, leave_type_id=leave_type_id).order_by(LeaveRequest.id.desc()).first()
        if leave_request:
            start_dt = leave_request.start_date
            end_dt = leave_request.end_date
        else:
            start_dt = None
            end_dt = None

    # Notion Integration to get tasks overlapping leave dates
    tasks_text = "No overlapping tasks."
    if start_dt and end_dt:
        notion_client = NotionClient(auth=NOTION_API_KEY)

        # Map slack user IDs to Notion IDs - maintain this properly
        slack_to_notion_user_map = {
            "U09DHCLQK8A": "26bd872b-594c-81cd-8aa1-0002dc180e8b"  # example
        }
        notion_user_id = slack_to_notion_user_map.get(user_id)
        
        if notion_user_id:
            tasks = fetch_user_tasks_with_deadlines(
                notion_client,
                NOTION_TASKS_DB_ID,
                notion_user_id,
                start_dt,
                end_dt
            )
            if tasks:
                tasks_text = "\n".join([f"• {t['name']} (Due: {t['due'] or 'N/A'}) [{t['project'] or 'Unknown'}]" for t in tasks])

    hr_message = (
        f"Leave request from <@{user_id}> for *{requested_days} day(s)* was *{decision_text}* by <@{manager_id}>.\n"
        f"Tasks overlapping with the leave date:\n{tasks_text}"
    )

    client.chat_postMessage(
        channel=HR_CHANNEL_ID,
        text=hr_message,
    )

    # Update leave request status and user leave balance
    with flask_app.app_context():
        leave_request = LeaveRequest.query.filter_by(
            user_id=user_id,
            leave_type_id=leave_type_id,
            status="pending"
        ).order_by(LeaveRequest.id.desc()).first()
        if leave_request:
            leave_request.status = decision_text
            db.session.commit()
        if decision == "approved":
            user_balance_record = UserLeaveBalance.query.filter_by(user_id=user_id, leave_type_id=leave_type_id).first()
            if user_balance_record:
                user_balance_record.leave_balance = max(0, user_balance_record.leave_balance - requested_days)
                db.session.commit()

#over over

@app.action("discuss_button")
def handle_discuss_action(ack, body, client, logger):
    ack()
    user_id, _, requested_days, leave_type_id = body["actions"][0]["value"].split("|")
    manager_id = body["user"]["id"]
    try:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=manager_id,
            text="Discussion session started. The employee will join shortly to discuss the leave request.",
            thread_ts=body["message"]["ts"]
        )
    except Exception as e:
        logger.error(f"Failed to send ephemeral discussion confirmation to manager: {e}")
    USER_DISCUSSION_STATE[user_id] = True
    try:
        client.chat_postMessage(
            channel=user_id,
            text=(
                f"<@{manager_id}> wants to discuss your leave request for *{requested_days} day(s)*.\n"
                "Please schedule a meeting and complete the discussion.\n"
                "Once done, you may use the *Re-request Leave* button below to resubmit your request."
            ),
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": (
                    f"<@{manager_id}> wants to discuss your leave request for *{requested_days} day(s)*.\n"
                    "Please schedule a meeting and complete the discussion.\n"
                    "Once done, you may use the *Re-request Leave* button below to resubmit your request."
                )}},
                {"type": "actions", "block_id": "rerequest_block", "elements": [{
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Re-request Leave"},
                    "style": "primary",
                    "value": f"{user_id}|{requested_days}|{leave_type_id}",
                    "action_id": "rerequest_button",
                }]}
            ],
        )
        dm = client.conversations_open(users=manager_id)
        manager_channel = dm["channel"]["id"]
        client.chat_postMessage(
            channel=manager_channel,
            text=(
                f"📢 The user <@{user_id}> has been notified about your request to discuss "
                f"their leave request for *{requested_days} day(s)*."
            ),
        )
    except Exception as e:
        logger.error(f"Failed to send discussion DM: {e}")

@app.action("rerequest_button")
def handle_rerequest_button(ack, body, client, logger):
    ack()
    user_id, requested_days, leave_type_id = body["actions"][0]["value"].split("|")
    requested_days = int(requested_days)
    leave_type_id = int(leave_type_id)
    manager_id = MANAGER_USER_ID
    try:
        if not USER_DISCUSSION_STATE.get(user_id, False):
            client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text="Re-request blocked",
                blocks=[{
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "⚠️ You need to discuss this leave with your manager before re-requesting."}
                }]
            )
            return
        dm = client.conversations_open(users=manager_id)
        channel_id = dm["channel"]["id"]
        message = (
            f"<@{user_id}> has re-requested leave after discussion for *{requested_days} day(s)*.\n"
            "_Note: The user has already discussed this leave request with the manager._"
        )
        client.chat_postMessage(
            channel=channel_id,
            text="Leave re-request pending approval",
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": message}},
                {"type": "actions", "block_id": "final_approval_buttons", "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Approve"}, "style": "primary",
                     "value": f"{user_id}|approved|{requested_days}|{leave_type_id}", "action_id": "approve_button" },
                    {"type": "button", "text": {"type": "plain_text", "text": "Decline"}, "style": "danger",
                     "value": f"{user_id}|declined|{requested_days}|{leave_type_id}", "action_id": "decline_button" }
                ]}
            ],
        )
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            text="Re-request submitted",
            blocks=[{
                "type": "section",
                "text": {"type": "mrkdwn", "text": "✅ Your leave re-request has been submitted. Your manager will review it and respond shortly."}
            }]
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
    with flask_app.app_context():
        db.create_all()
        initialize_leave_types_and_user_balances()
    flask_app.run(host="0.0.0.0", port=8000)
