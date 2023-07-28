import requests
import slack
import os
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, Response
from slackeventsapi import SlackEventAdapter

# For environment variables
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)
# Flask init
app = Flask(__name__)
slack_event_adapter = SlackEventAdapter(os.environ['SIGNING_SECRET'], '/slack/events', app)
PAGERDUTY_TOKEN = os.environ['PAGERDUTY_TOKEN']
PAGERDUTY_SCHEDULE_ID = os.environ['PAGERDUTY_SCHEDULE_ID']
client = slack.WebClient(token=os.environ['SLACK_TOKEN'])
BOT_ID = client.api_call("auth.test")['user_id'] # Bot ID

@app.route('/help', methods=['POST'])
def help():
    form = request.form
    channel_name = form.get('channel_name')
    user_id = form.get('user_id')

    message = "```/pagerduty-list - List the current week's on-call schedule\n/pagerduty-swap (@user) - Swap your on-call shift with another user\n```"

    print('#'+channel_name)
    client.chat_postEphemeral(channel='#'+channel_name, text=message, user=user_id)

    return Response(content_type='text/plain'), 202

@app.route('/pagerduty-list', methods=['POST'])
def pagerduty_list():
    form = request.form
    user_id = form.get('user_id')
    channel_name = form.get('channel_name')

    headers = {"Authorization": "Token token=" + PAGERDUTY_TOKEN}
    response = requests.get(f'https://api.pagerduty.com/schedules/{PAGERDUTY_SCHEDULE_ID}', headers=headers)
    data = response.json()
    scheduled_users = get_scheduled_users(data)

    current_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    # Filter out users with end dates in the past and adjust start date for the first user
    filtered_users = []
    for name, start_date, end_date in scheduled_users:
        if end_date >= current_datetime:
            # If the start date is in the past, adjust it to the current date
            start_date = max(start_date, current_datetime)
            filtered_users.append((name, start_date, end_date))

    message = ""
    for name, start_date, end_date in filtered_users:
        formatted_start_date = start_date.strftime('%Y-%m-%d')
        formatted_end_date = end_date.strftime('%Y-%m-%d')
        message += f"{name:15} {formatted_start_date:10} - {formatted_end_date:20}\n"

    client.chat_postEphemeral(channel='#'+channel_name, text=f"```{message}```", user=user_id)

    return Response(content_type='text/plain'), 202

@app.route('/swap', methods=['POST'])
def swap():
    form = request.form
    user_id = form.get('user_id')
    user_id_to_swap = parseUserId(form.get('text'))
    channel_name = form.get('channel_name')

    if user_id == user_id_to_swap:
        client.chat_postEphemeral(channel='#' + channel_name, text=f'You cannot swap shifts with yourself.', user=user_id)
        return Response(content_type='text/plain'), 202

    user1Info = client.users_info(user=user_id)
    user2Info = client.users_info(user=user_id_to_swap)

    user1Name = user1Info['user']['profile']['real_name']
    user2Name = user2Info['user']['profile']['real_name']

    switch_schedules(user1Name, user2Name, user_id, channel_name, user_id_to_swap)

    return Response(content_type='text/plain'), 202
# Parses the user id from the POST request
def parseUserId(user_id):
    start_index = user_id.find('@') + 1
    end_index = user_id.find('|')
    user_id = user_id[start_index:end_index]
    return user_id
def switch_schedules(user1Name, user2Name, userId, channelName, userIdToSwap):

    endpoint_url = f"https://api.pagerduty.com/schedules/{PAGERDUTY_SCHEDULE_ID}"

    # Prepare the headers with authentication and content type.
    headers = {
        "Authorization": f"Token token={PAGERDUTY_TOKEN}",
        "Content-Type": "application/json"
    }

    # Fetch the current schedule details for the given schedule ID.
    response = requests.get(endpoint_url, headers=headers)

    if response.status_code == 200:
        schedule_data = response.json()
        schedule_layers = schedule_data['schedule']['schedule_layers']

        #Write a function that compares the user1Name and user2Name to data['schedule']['users'][index]['summary'] in the schedule_layers

        user_id1 = None
        user_id2 = None
        for i, layer in enumerate(schedule_layers):
            users = layer.get('users', [])
            for j, user in enumerate(users):
                if user['user']['summary'] == user1Name:
                    user_id1 = user['user']['id']
                elif user['user']['summary'] == user2Name:
                    user_id2 = user['user']['id']
        if user_id1 is None:
            client.chat_postEphemeral(
                channel='#' + channelName,
                text=f'You are not apart of this schedule.',
                user=userId
            )
            return Response(content_type='text/plain'), 202
        # Find the positions of the two users in the schedule layers.
        position_user1 = None
        position_user2 = None
        for i, layer in enumerate(schedule_layers):
            users = layer.get('users', [])
            for j, user in enumerate(users):
                if user['user']['id'] == user_id1:
                    position_user1 = (i, j)
                elif user['user']['id'] == user_id2:
                    position_user2 = (i, j)

        tempUser = schedule_layers[position_user1[0]]['users'][position_user1[1]]

        # Swap the users in the schedule layers.
        if position_user1 is not None and position_user2 is not None:
            schedule_layers[position_user1[0]]['users'][position_user1[1]] = schedule_layers[position_user2[0]]['users'][position_user2[1]]
            schedule_layers[position_user2[0]]['users'][position_user2[1]] = tempUser

            # Prepare the payload with the updated schedule layers.
            payload = {
                "schedule": {
                    "schedule_layers": schedule_layers,
                    "time_zone": schedule_data['schedule']['time_zone']  # Include the time zone
                }
            }

            # Make the PUT request to update the schedule with the new schedule layers.
            response = requests.put(endpoint_url, headers=headers, json=payload)

            if response.status_code == 200:
                client.chat_postEphemeral(
                    channel='#' + channelName,
                    text=f'Successfully switched shifts with <@{userIdToSwap}>.',
                    user=userId
                )
            else:
                client.chat_postEphemeral(
                    channel='#' + channelName,
                    text=f'Failed to switch shifts with <@{userIdToSwap}>.',
                    user=userId
                )
        else:
            client.chat_postEphemeral(
                channel='#' + channelName,
                text=f'User <@{userIdToSwap}> not found in the schedule.',
                user=userId
            )
    else:
        client.chat_postEphemeral(channel='#' + channelName, text=f'Could not retrieve schedule details.', user=userId)
def get_scheduled_users(schedule_data):
    schedule_start = datetime.fromisoformat(schedule_data['schedule']['schedule_layers'][0]['rotation_virtual_start'][:-6])
    turn_length = timedelta(seconds=schedule_data['schedule']['schedule_layers'][0]['rotation_turn_length_seconds'])
    users = schedule_data['schedule']['schedule_layers'][0]['users']

    scheduled_users = []

    for index, user in enumerate(users):
        user_name = user['user']['summary']
        start_date = schedule_start + (turn_length * index)
        end_date = start_date + timedelta(weeks=1)
        scheduled_users.append((user_name, start_date, end_date))

        # Sort the scheduled users by their scheduled dates
        scheduled_users.sort(key=lambda x: x[1])

    return scheduled_users

if __name__ == "__main__":
    app.run(debug=False, port=5000)
