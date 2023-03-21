import glob
import os
import random
import time
from datetime import datetime

# This hides the "Hello from the pygame..." message
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import click
import pygame
import requests

CATEGORIES = [
    "birds",
    "chainsaw",
    "fire",
    "handsaw",
    "helicopter",
]

SOUND_FILES = {
    category: glob.glob(f"soundfiles/{category}_*.wav") for category in CATEGORIES
}

SOUND_DURATION = 5.0


def info(*args, **kwargs):
    print(f"{datetime.now()} [INFO] -", *args, **kwargs)


@click.command()
@click.option(
    "-u",
    "--url",
    default="https://perceval.elen.ucl.ac.be",
    envvar="LEADERBOARD_URL",
    show_default=True,
    show_envvar=True,
    help="Base API url.",
)
@click.option(
    "-k",
    "--key",
    required=True,
    envvar="LEADERBOARD_ADMIN_KEY",
    show_envvar=True,
    help="Key granting admin rights",
)
@click.option(
    "-r",
    "--random-key",
    default=None,
    envvar="LEADERBOARD_RANDOM_KEY",
    show_envvar=True,
    help="Key for a group that will always guess randomly",
)
def main(url, key, random_key):
    """Play "correct" sound according to the leaderboard status."""

    # Wait for server to be up
    # and checks if admin rights
    while True:
        response = requests.get(f"{url}/lelec2103/leaderboard/check/{key}")

        code = response.status_code

        if code == 200:
            assert response.json()["admin"], "key must belong to an admin!"

            if random_key:
                response = requests.get(
                    f"{url}/lelec2103/leaderboard/check/{random_key}"
                )

                if response.status_code != 200:
                    raise ValueError(response.json())

            break
        elif code == 401:
            raise ValueError(response.json())
        else:
            info("Waiting server to be ready")
            time.sleep(0.2)

    pygame.mixer.init()
    played_sounds = set()

    while True:
        start = time.time()
        json = requests.get(f"{url}/lelec2103/leaderboard/status/{key}").json()
        delay = time.time() - start
        info(f"Took {delay:.4f}s for the status request")

        if json["paused"]:
            info("Leaderboard is paused")
            time.sleep(0.2)
            continue

        info(json)

        current_round = json["current_round"]
        current_lap = json["current_lap"]
        time_before_next_lap = json["time_before_next_lap"]
        time_before_playing = json["time_before_playing"]
        category = json["current_correct_guess"]

        sound_key = (current_round + 1, current_lap + 1)

        if sound_key in played_sounds:
            info(f"A song has already been played for round, lap: {sound_key}")
            time.sleep(min(.2, time_before_next_lap))
            continue

        played_sounds.add(sound_key)

        sound_file = random.choice(SOUND_FILES[category])

        if time_before_playing < 0:
            info(f"Too late for playing: {category}")
            time.sleep(time_before_next_lap)
            continue

        info(f"Playing sound in {time_before_playing}")

        time.sleep(time_before_playing)
        sound = pygame.mixer.Sound(sound_file)
        sound.play()
        start = time.time()
        info("Playing sound now")

        # Admins are always correct :-)
        requests.patch(f"{url}/lelec2103/leaderboard/submit/{key}/{category}")

        if random_key:  # Random player
            guess = random.choice(CATEGORIES)
            requests.patch(f"{url}/lelec2103/leaderboard/submit/{random_key}/{guess}")

        delay = time.time() - start
        time.sleep(max(0, SOUND_DURATION - delay))


if __name__ == "__main__":
    main()
