# Slack Leave Management App

A Slack-integrated leave management application that allows employees to submit leave requests, provides managers with approval/decline/discussion options, and notifies HR. Built with **Python**, **Slack Bolt**, and **Flask**.

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
| [Contributing](#contributing) | Guidelines for contributing |


---

## Overview

The **Slack Leave Management App** simplifies leave requests for employees and streamlines approvals for managers. Users can submit leave requests via a Slack modal, specify dates and reasons, optionally provide proof, and get instant notifications about the request status. Managers can approve, decline, or request discussion before a decision, and HR is kept informed of all leave activity.

---

## Features

- Submit leave requests directly in Slack using `/leave_app` command.
- Select leave type (Vacation, Sick Leave, Personal, Other).
- Choose start and end dates using a date picker.
- Optional submission of proof details for leave requests.
- Manager receives leave requests with **Approve**, **Decline**, and **Discuss** options.
- Users can re-request leave after discussion with the manager.
- Automatic leave balance tracking.
- Notifications sent to HR on all leave decisions.
- Web interface powered by Flask for running the app.

---

## Tech Stack

- **Python 3.9+**
- **Slack Bolt** for Slack app integration
- **Flask** for the web server and Slack event handling
- **Slack API** for messaging, modals, and interactions

---

## Setup & Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/yourusername/slack-leave-app.git
   cd slack-leave-app

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Set environment variables:**

   See [Environment Variables](#environment-variables) below.

4. **Run the Flask app:**

   ```bash
   python main.py
   ```

5. **Expose the server for Slack events (optional for local testing):**

   ```bash
   ngrok http 8000
   ```

---

## Environment Variables

| Variable               | Description                                 |
| ---------------------- | ------------------------------------------- |
| `SLACK_BOT_TOKEN`      | Bot user OAuth token from Slack             |
| `SLACK_SIGNING_SECRET` | Signing secret for verifying Slack requests |
| `MANAGER_USER_ID`      | Slack user ID of the manager                |
| `HR_CHANNEL_ID`        | Slack channel ID for HR notifications       |

Example `.env`:

```env
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret
MANAGER_USER_ID=U09E2SQFTLY
HR_CHANNEL_ID=U09DJQKJH1R
```

---

## Usage

1. In Slack, type `/leave_app` to open the leave request modal.
2. Fill in:

   * Reason for leave
   * Start and end dates
   * Optional proof details
3. Submit the request.
4. Manager receives the request with **Approve**, **Decline**, or **Discuss** buttons.
5. HR gets notified on final decision.
6. If discussion is needed, users can **Re-request** leave after resolving concerns.

---

## Project Structure

```
slack-leave-app/
├── main.py             # Main Flask & Slack app code
├── requirements.txt    # Python dependencies
├── README.md           # Project documentation
└── .env                # Environment variables (not committed)
```

* **main.py**: Contains all Slack command, modal, action handlers, and Flask routes.
* **USER\_LEAVE\_BALANCES**: Mock data store for leave balances.
* **USER\_DISCUSSION\_STATE**: Tracks if a user has discussed leave before re-request.

---

## Contributing

1. Fork the repository.
2. Create a new branch: `git checkout -b feature/your-feature`.
3. Make your changes and commit: `git commit -m "Add feature"`.
4. Push to your branch: `git push origin feature/your-feature`.
5. Open a Pull Request for review.


```
Do you want me to add that?
```
