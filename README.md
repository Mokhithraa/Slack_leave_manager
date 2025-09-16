# Slack Leave Management App

A Slack-integrated leave management system that allows employees to submit leave requests, provides managers with approval/decline/discussion options, tracks leave balances, and notifies HR with task overlap details from Notion. Built with **Python**, **Slack Bolt**, **Flask**, **SQLAlchemy**, and **Notion API**.

---

## Table of Contents

| Section | Description |
|---------|-------------|
| [Overview](#overview) | High-level description of the project |
| [Features](#features) | Key functionalities provided by the app |
| [Tech Stack](#tech-stack) | Technologies and libraries used |
| [Setup & Installation](#setup--installation) | How to set up the app locally |
| [Environment Variables](#environment-variables) | Required environment variables |
| [Usage](#usage) | How to use the Slack commands and features |
| [Project Structure](#project-structure) | File and folder structure explanation |
| [Project Evolution](#project-evolution) | Improvements made from the initial version |
| [Contributing](#contributing) | Guidelines for contributing |

---

## Overview

The **Slack Leave Management App** simplifies employee leave requests and streamlines approvals for managers and HR.  
Employees can request leave via Slack slash commands, managers can take action with a single click, and HR gets automated notifications with task and project conflicts pulled directly from Notion.  
The app also enforces organizational policies like notice periods, leave balances, and validation against weekends or holidays.

---

## Features

- **Leave Requests**  
  - `/applyforleave` opens a modal to request leave.  
  - Specify leave type (Vacation, Sick Leave, Personal, Other).  
  - Choose start and end dates with a date picker.  
  - Add a reason and optional proof details.  
  - Smart validations:  
    - Minimum notice period checks.  
    - Sick leave allowed with shorter notice.  
    - Weekends/holidays excluded.  
    - Leave balance verification.

- **Manager Workflow**  
  - Requests sent directly to the manager via Slack DM.  
  - One-click options: **Approve**, **Decline**, or **Discuss**.  
  - Discussion state allows re-submission after clarification.  
  - Approved/declined leaves automatically update balances.

- **HR Notifications**  
  - HR channel is notified of all decisions.  
  - Notion tasks overlapping with leave dates are highlighted.  
  - Provides visibility into project timelines and dependencies.

- **Additional Commands**  
  - `/leave_balance` → Check your current leave balance.  
  - `/whos_away` → View employees on leave in the next 7 days, 30 days, or current month.  

---

## Tech Stack

- **Python 3.9+**
- **Slack Bolt** → Slack integration (events, commands, modals)
- **Flask** → Web server for handling Slack requests
- **SQLAlchemy** → Persistent database (SQLite/Postgres)
- **Notion API** → Task and project tracking integration
- **Slack API** → Messaging, modals, and user interactions

---

## Setup & Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/yourusername/slack-leave-app.git
   cd slack-leave-app
2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
3. **Set environment variables:**

   See [Environment Variables](#environment-variables) below.

4. **Run the Flask app:**

   ```bash
   python main.py
5. **Expose the server for Slack events (optional for local testing):**

   ```bash
   ngrok http 8000
## Environment Variables

| Variable               | Description                                 |
| ---------------------- | ------------------------------------------- |
| `SLACK_BOT_TOKEN`      | Bot user OAuth token from Slack             |
| `SLACK_SIGNING_SECRET` | Signing secret for verifying Slack requests |
| `MANAGER_USER_ID`      | Slack user ID of the manager                |
| `HR_CHANNEL_ID`        | Slack channel ID for HR notifications       |
| `DATABASE_URL`         | SQLAlchemy database connection string       |
| `NOTION_API_KEY`       | Integration key for Notion API              |
| `NOTION_TASKS_DB_ID`   | Notion database ID for tasks                |

Example `.env`:

```env
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret
MANAGER_USER_ID=U09E2SQFTLY
HR_CHANNEL_ID=U09DJQKJH1R
DATABASE_URL=sqlite:///leave_app.db
NOTION_API_KEY=secret_xxxxx
NOTION_TASKS_DB_ID=xxxxxxxxxxxxxxxxxxxx
```
---
## Usage

1. In Slack, type `/applyforleave` to open the leave request modal.
2. Fill in:
   - Leave type  
   - Reason for leave  
   - Start and end dates  
   - Optional proof details  
3. Submit the request.  
4. Manager receives a DM with **Approve**, **Decline**, or **Discuss** options.  
5. HR is notified of all final decisions, with overlapping Notion tasks flagged.  
6. Use `/leave_balance` to check your remaining leaves.  
7. Use `/whos_away` to see who is on leave.  

---
## Project Structure

```
slack-leave-app/
├── main.py             # Contains Slack commands, action handlers, and Flask routes.
├── requirements.txt    # Python dependencies
├── README.md           # Project documentation
└── .env                # Environment variables (ignored in git)
```

---

## Project Evolution

- **Initial Version:**  
  - Basic leave request/approval system.  
  - Mock balances stored in-memory.  
  - Single `/leave_app` command.  

- **Current Version:**  
  - SQLAlchemy-backed persistent storage.  
  - Multiple slash commands: `/applyforleave`, `/leave_balance`, `/whos_away`.  
  - Advanced validations (notice period, sick leave rules, weekends).  
  - Notion integration for deadline/task overlap detection.  
  - Manager workflow with Approve/Decline/Discuss options.  
  - HR notified with detailed project/task context.  

---

## Contributing

1. Fork the repository.  
2. Create a new branch:  
   ```bash
   git checkout -b feature/your-feature

