import random
import time
from enum import Enum
from pathlib import Path
from typing import List

from flask_login import LoginManager, UserMixin
from flask_sqlalchemy import SQLAlchemy
from pydantic import (
    BaseModel,
    Extra,
    PositiveFloat,
    PositiveInt,
    PrivateAttr,
    confloat,
    conint,
    constr,
    root_validator,
    validator,
)
from sqlalchemy import Enum as SQLEnum
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

login_manager = LoginManager()

DEFAULT_CONFIG_PATH = Path(".config.json")


class GroupConfig(BaseModel):
    key: constr(min_length=1, max_length=128)
    name: constr(min_length=1, max_length=128)
    admin: bool = False


class Guess(str, Enum):
    birds = "birds"
    chainsaw = "chainsaw"
    fire = "fire"
    handsaw = "handsaw"
    helicopter = "helicopter"
    nothing = "nothing"
    received = "received"
    disqualified = "disqualified"

    @classmethod
    def possible_values(self):
        return [
            guess
            for guess in Guess
            if guess not in [Guess.nothing, Guess.received, Guess.disqualified]
        ]


class Answer(BaseModel):
    guess: Guess
    correct: bool = False
    hide: bool = False


class RoundConfig(BaseModel):
    lap_count: PositiveInt = 20
    lap_duration: PositiveFloat = 13.0
    only_check_for_presence: bool = False


class RoundsConfig(BaseModel):
    rounds: List[RoundConfig] = [
        RoundConfig(only_check_for_presence=True),
        RoundConfig(),
        RoundConfig(),
        RoundConfig(),
        RoundConfig(),
    ]
    seed: PositiveInt = 1234
    start_paused: bool = True
    restart_when_finished: bool = False
    pause_between_rounds = True
    latency_margin: PositiveFloat = 1.0
    delay_before_playing: PositiveFloat = 2.0
    delay_after_playing: PositiveFloat = 1.0
    sound_duration: PositiveFloat = 5.0
    __answers: List[List[Guess]] = PrivateAttr()
    __play_delays: List[List[PositiveFloat]] = PrivateAttr()
    __round_start_time: float = PrivateAttr()
    __time_when_paused: float = PrivateAttr()
    __paused: bool = PrivateAttr()
    __current_round: conint(ge=0) = PrivateAttr()
    __current_lap: conint(ge=0) = PrivateAttr()
    __finished: bool = PrivateAttr()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        random.seed(self.seed)

    @root_validator
    def validate_timing(cls, values):
        rounds = values.get("rounds")
        latency_margin = values.get("latency_margin")
        delay_before_playing = values.get("delay_before_playing")
        delay_after_playing = values.get("delay_after_playing")
        sound_duration = values.get("sound_duration")
        total = (
            latency_margin + delay_before_playing + delay_after_playing + sound_duration
        )

        for round_config in rounds:
            lap_duration = round_config.lap_duration
            assert (
                lap_duration >= total
            ), f"Lap duration is not long enough: {lap_duration} is shorted than {total}"

        return values

    def restart(self):
        Submission.clear()

        possibles_answers = Guess.possible_values()

        self.__answers = [
            random.choices(possibles_answers, k=round_config.lap_count)
            for round_config in self.rounds
        ]
        total = (
            self.latency_margin
            + self.delay_before_playing
            + self.delay_after_playing
            + self.sound_duration
        )
        start = self.delay_before_playing

        self.__play_delays = [
            [
                start + random.random() * (round_config.lap_duration - total)
                for _ in range(round_config.lap_count)
            ]
            for round_config in self.rounds
        ]

        self.__round_start_time = time.time()
        self.__time_when_paused = self.__round_start_time
        self.__paused = True
        self.__current_round = 0
        self.__finished = False

        if not self.start_paused:
            self.play()

    def time(self) -> float:
        if self.__paused:
            return self.__time_when_paused

        return time.time()

    def get_current_round_config(self) -> RoundConfig:
        return self.rounds[self.get_current_round()]

    def get_current_time_within_lap(self) -> float:
        elapsed = self.time() - self.__round_start_time
        lap_duration = self.get_current_round_config().lap_duration

        return elapsed % lap_duration

    def get_current_play_delay(self) -> float:
        return self.__play_delays[self.get_current_round()][self.get_current_lap()]

    def accepts_submissions(self) -> bool:
        current_time = self.get_current_time_within_lap()
        current_play_delay = self.get_current_play_delay()

        return (
            current_play_delay
            <= current_time
            <= current_play_delay + self.sound_duration + self.latency_margin
        )

    def play(self):
        if not self.__paused:
            return

        self.__round_start_time += time.time() - self.__time_when_paused
        self.__paused = False

    def pause(self):
        if self.__paused:
            return

        self.__time_when_paused = time.time()
        self.__paused = True

    def get_current_round(self) -> int:
        return self.__current_round

    def get_current_lap(self) -> int:
        elapsed = self.time() - self.__round_start_time
        lap_duration = self.rounds[self.get_current_round()].lap_duration

        current_lap = elapsed // lap_duration

        if current_lap >= self.get_current_number_of_laps():
            if self.get_current_round() + 1 == self.get_number_of_rounds():
                if self.restart_when_finished:
                    self.restart()
                    return 0
                else:
                    self.__finished = True
                    self.pause()
                    return self.get_current_number_of_laps() - 1
            else:
                self.__current_round += 1
                self.__round_start_time = time.time()

                if self.pause_between_rounds:
                    self.pause()

                return 0  # First lap of next round

        return int(current_lap)

    def get_current_correct_guess(self) -> Guess:
        return self.__answers[self.get_current_round()][self.get_current_lap()]

    def get_number_of_rounds(self) -> int:
        return len(self.rounds)

    def get_current_number_of_laps(self) -> int:
        return self.rounds[self.get_current_round()].lap_count

    def get_current_round_answers(self) -> List[Guess]:
        return self.__answers[self.get_current_round()]

    def is_paused(self) -> bool:
        return self.__paused

    def time_before_next_lap(self) -> float:
        if self.__finished:
            return 0.0

        elapsed = self.time() - self.__round_start_time
        lap_duration = self.rounds[self.get_current_round()].lap_duration

        return lap_duration - elapsed % lap_duration

    def time_before_playing(self) -> float:
        if self.__finished:
            return -1.0

        elapsed = self.time() - self.__round_start_time
        lap_duration = self.rounds[self.get_current_round()].lap_duration
        play_delay = self.get_current_play_delay()

        return play_delay - elapsed % lap_duration

    def is_finished(self) -> bool:
        return self.__finished


class LeaderboardRow(BaseModel):
    name: str
    answers: List[Answer]
    score: float


class LeaderboardStatus(BaseModel):
    current_correct_guess: Guess
    current_round: conint(ge=0)
    current_lap: conint(ge=0)
    number_of_rounds: conint(ge=0)
    number_of_laps: conint(ge=0)
    paused: bool
    time_before_next_lap: float
    time_before_playing: float
    finished: bool
    leaderboard: List[LeaderboardRow]

    class Config:
        extra = Extra.forbid


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50))
    password_hash = db.Column(db.String(256))

    def __repr__(self):
        return f"User({self.username})"

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password_hash(self, password):
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))


class Submission(db.Model):
    """Holds /submit request from a given group."""

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    seed = db.Column(db.Integer)
    round = db.Column(db.Integer)
    lap = db.Column(db.Integer)
    key = db.Column(db.String(128))
    guess = db.Column(SQLEnum(Guess))
    disqualified = db.Column(db.Boolean)

    @classmethod
    def get_submissions(cls, key: str, round: int, lap: int) -> List[Guess]:
        """
        Returns the guesses submitted by a group for a given round and lap.

        If no guesses were submitted, [Guess.nothing] is returned.

        Guesses are sorted with earliest first, oldest last.
        """
        guesses = (
            cls.query.with_entities(Submission.guess)
            .filter_by(key=key, round=round, lap=lap)
            .order_by(cls.timestamp.desc())
            .all()
        )

        if guesses:
            return [guess[0] for guess in guesses]

        return [Guess.nothing]

    @classmethod
    def is_disqualified(cls, key: str, round: int, lap: int) -> bool:
        """
        Returns true if a group was disqualified for a given round and lap.
        """
        disqualified = (
            cls.query.with_entities(Submission.disqualified)
            .filter_by(key=key, round=round, lap=lap)
            .all()
        )

        for (is_disqualified,) in disqualified:
            if is_disqualified:
                return True
        return False

    @classmethod
    def clear(cls):
        cls.query.delete()
        db.session.commit()


class Config(BaseModel):
    group_configs: List[GroupConfig] = []
    rounds_config: RoundsConfig = RoundsConfig()

    class Config:
        extra = Extra.forbid

    @validator("group_configs")
    def unique_names_and_keys(cls, v):
        keys = set()
        names = set()

        for group_config in v:
            key = group_config.key
            name = group_config.name

            if key in keys:
                raise ValueError(f"duplicate key found: `{key}`")
            keys.add(key)

            if name in names:
                raise ValueError(f"duplicate name found: `{name}`")
            names.add(name)

        return v

    def save_to(self, path: str):
        with open(path, "w") as f:
            f.write(self.json(indent=2))

    def get_group_by_name(self, name: str) -> GroupConfig:
        try:
            return next(
                filter(
                    lambda group_config: group_config.name == name, self.group_configs
                )
            )
        except StopIteration:
            raise IndexError(f"name `{name}` not found")

    def get_group_by_key(self, key: str) -> GroupConfig:
        try:
            return next(
                filter(lambda group_config: group_config.key == key, self.group_configs)
            )
        except StopIteration:
            raise IndexError(f"key `{key}` not found")

    def get_leaderboard_status(self) -> LeaderboardStatus:

        current_correct_guess = self.rounds_config.get_current_correct_guess()
        current_round = self.rounds_config.get_current_round()
        current_lap = self.rounds_config.get_current_lap()
        number_of_rounds = self.rounds_config.get_number_of_rounds()
        number_of_laps = self.rounds_config.get_current_number_of_laps()
        paused = self.rounds_config.is_paused()
        time_before_next_lap = self.rounds_config.time_before_next_lap()
        time_before_playing = self.rounds_config.time_before_playing()
        finished = self.rounds_config.is_finished()

        correct_answers = self.rounds_config.get_current_round_answers()

        rows = []
        for group_config in self.group_configs:
            answers = []
            score = .0
            for lap, correct_answer in enumerate(correct_answers):
                # Getting last submission
                guess = Submission.get_submissions(
                    group_config.key, current_round, lap
                )[-1]

                if Submission.is_disqualified(group_config.key, current_round, lap):
                    guess = Guess.disqualified
                    correct = False
                    score -= .5

                elif (
                    self.rounds_config.get_current_round_config().only_check_for_presence
                ):
                    if guess != Guess.nothing:
                        guess = Guess.received
                        correct = True
                    else:
                        correct = False
                else:
                    correct = guess == correct_answer

                if correct:
                    score += 1.

                hide = lap > current_lap

                answers.append(Answer(guess=guess, correct=correct, hide=hide))

            rows.append(
                LeaderboardRow(name=group_config.name, answers=answers, score=score)
            )

        return LeaderboardStatus(
            current_correct_guess=current_correct_guess,
            current_round=current_round,
            current_lap=current_lap,
            number_of_rounds=number_of_rounds,
            number_of_laps=number_of_laps,
            paused=paused,
            time_before_next_lap=time_before_next_lap,
            time_before_playing=time_before_playing,
            finished=finished,
            leaderboard=rows,
        )
