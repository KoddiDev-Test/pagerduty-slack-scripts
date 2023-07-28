from pathlib import Path
from datetime import datetime, timedelta, timezone
import requests
import slack
import os

from dotenv import load_dotenv

# Load environment variables
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

# Initialize Slack WebClient and PagerDuty API constants
SLACK_BOT_TOKEN = os.environ['SLACK_TOKEN']
PAGERDUTY_SCHEDULE_ID = os.environ['PAGERDUTY_SCHEDULE_ID']
PAGERDUTY_TOKEN = os.environ['PAGERDUTY_TOKEN']

# Initialize Slack WebClient
client = slack.WebClient(token=SLACK_BOT_TOKEN)

# Function to get the current on-call user and the next user
def get_current_on_call_user():
    headers = {"Authorization": "Token token=" + PAGERDUTY_TOKEN}
    response = requests.get(f'https://api.pagerduty.com/schedules/{PAGERDUTY_SCHEDULE_ID}', headers=headers)
    data = response.json()
    scheduled_users = get_scheduled_users(data)
    now = datetime.now(timezone.utc)

    current_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    filtered_users = [(name, id, start_date, end_date) for name, id, start_date, end_date in scheduled_users if end_date >= current_datetime]
    filtered_users.sort(key=lambda x: x[2])

    return filtered_users[0][1], filtered_users[1][1]

# Function to get the scheduled users from PagerDuty
def get_scheduled_users(schedule_data):
    schedule_start = datetime.fromisoformat(schedule_data['schedule']['schedule_layers'][0]['rotation_virtual_start'][:-6])
    turn_length = timedelta(seconds=schedule_data['schedule']['schedule_layers'][0]['rotation_turn_length_seconds'])
    users = schedule_data['schedule']['schedule_layers'][0]['users']

    scheduled_users = []

    for index, user in enumerate(users):
        user_id = user['user']['id']
        user_name = user['user']['summary']
        start_date = schedule_start + (turn_length * index)
        end_date = start_date + timedelta(weeks=1)
        scheduled_users.append((user_name, user_id, start_date, end_date))

    return scheduled_users

# Function to get user email by their ID
def get_user_email_by_id(user_id):
    headers = {"Authorization": f"Token token={PAGERDUTY_TOKEN}"}
    response = requests.get(f"https://api.pagerduty.com/schedules/{PAGERDUTY_SCHEDULE_ID}/users", headers=headers)
    data = response.json()

    for user in data['users']:
        if user['id'] == user_id:
            return user['email']

    return None

# Function to find Slack ID by email
def find_slack_id_by_email(user_email):
    try:
        response = client.users_lookupByEmail(email=user_email)
        if response['ok']:
            return response['user']['id']
    except slack.errors.SlackApiError as e:
        print(f"Error finding Slack ID: {e}")

    return None



    # You can handle additional error cases and responses as needed.
# Function to send Slack message
def send_slack_message(current_user_email, next_user_email):
    current_slack_id = find_slack_id_by_email(current_user_email)
    next_slack_id = find_slack_id_by_email(next_user_email)

    if current_slack_id:
        try:
            # Send the message to the user
            client.chat_postMessage(
                channel=current_slack_id,
                text=f'Your on-call duty has ended. Make sure to schedule a sync with the next dev on call <@{next_slack_id}>'
            )
            print(f"Message sent to {current_user_email}")
        except slack.errors.SlackApiError as e:
            print(f"Error sending Slack message: {e}")
    else:
        print(f"User with email {current_user_email} not found in Slack.")

if __name__ == "__main__":
    # Get the user ID of the current on-call user from PagerDuty
    on_call_user_current, on_call_user_next = get_current_on_call_user()

    if on_call_user_current:
        on_call_user_current_email = get_user_email_by_id(on_call_user_current)
        on_call_user_next_email = get_user_email_by_id(on_call_user_next)
        send_slack_message(on_call_user_current_email, on_call_user_next_email)
    else:
        print("No on-call user found.")
