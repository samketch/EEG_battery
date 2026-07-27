"""Experience Sampling Questionnaire (ESQ), shown once after each movie clip.

Presents every question from resources/ESQ/ESQ_Questions.csv via a 1-10
left/right-arrow rating scale -- the same response mechanic and log schema
as the original ESQ task, just invoked once per clip instead of once per
battery.
"""
import csv
import os
import random
import time

from psychopy import core, data, event, visual
from pyglet.window import key

RESOURCES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "ESQ")
QUESTIONS_PATH = os.path.join(RESOURCES_DIR, "ESQ_Questions.csv")
INSTRUCTIONS_PATH = os.path.join(RESOURCES_DIR, "ESQ_instr.txt")

# Same columns as the original taskbattery.resultdict schema, so ESQ logs
# stay compatible with how prior sessions' output was structured.
LOG_FIELDS = [
    "Timepoint", "Time", "Is_correct",
    "Experience Sampling Question", "Experience Sampling Response",
    "Task", "Task Iteration", "Participant ID", "Response_Key",
    "Auxillary Data", "Assoc Task",
]


def load_questions():
    try:
        questions = data.importConditions(QUESTIONS_PATH)
    except Exception as exc:
        raise RuntimeError("Could not read ESQ question file '{}': {}".format(QUESTIONS_PATH, exc)) from exc
    if not questions:
        raise RuntimeError("ESQ question file '{}' contains no questions.".format(QUESTIONS_PATH))
    return questions


def load_instructions():
    try:
        with open(INSTRUCTIONS_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        raise RuntimeError("Could not read ESQ instructions file '{}': {}".format(INSTRUCTIONS_PATH, exc)) from exc


def show_instructions(win, text):
    stim = visual.TextStim(win, text=text, font="sans", color="black")
    stim.draw()
    win.flip()
    event.waitKeys(keyList=["return"])
    win.flip()


class ESQLogger:
    """Appends ESQ rows for the whole session into one CSV, in the original schema."""

    def __init__(self, data_dir, participant_id, session_id, seed):
        participant_dir = os.path.join(data_dir, participant_id)
        os.makedirs(participant_dir, exist_ok=True)
        self.path = os.path.join(
            participant_dir, "{}_{}_{}_esq_log.csv".format(participant_id, session_id, seed)
        )
        is_new = not os.path.exists(self.path)
        self._file = open(self.path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=LOG_FIELDS)
        if is_new:
            self._writer.writeheader()
            self._flush()

    def _flush(self):
        self._file.flush()
        os.fsync(self._file.fileno())

    def log_row(self, **fields):
        row = {name: "" for name in LOG_FIELDS}
        row.update(fields)
        self._writer.writerow(row)
        self._flush()

    def close(self):
        self._file.close()


def run_esq(win, participant_id, movie_id, questions, logger, experiment_start):
    """Presents every question in `questions` once, in a fresh random order.

    `experiment_start` is the same core.getTime() reference movie onsets are
    measured against, so ESQ 'Time' values line up with the movie log.

    No experimenter-abort (Escape) handling here, unlike fixation/movie
    playback: RatingScale polls the keyboard itself each frame, and stealing
    key events out from under it (even just to check for Escape) can eat the
    keypress it's waiting for. This matches the original ESQ task's behavior.
    """
    # Re-seed from OS entropy so ESQ's question order/marker-start randomness
    # is never coupled to the experiment seed, matching the original task.
    random.seed()
    random.seed(a=random.randint(0, 10000))

    ordered_questions = list(questions)
    random.shuffle(ordered_questions)
    assoc_task = "Movie Task-{}".format(movie_id)

    rating_scale = visual.RatingScale(
        win, low=1, high=10, markerStart=4.5, precision=10, tickMarks=[1, 10],
        markerColor="black", textColor="black", lineColor="black",
        acceptPreText="Use the left and right arrow keys", acceptSize=3,
    )
    question_text = visual.TextStim(win, color="black", anchorHoriz="center", anchorVert="top")
    scale_high = visual.TextStim(win, wrapWidth=None, units="norm", color="black", pos=(1.0, -0.5), anchorHoriz="right", anchorVert="bottom")
    scale_low = visual.TextStim(win, wrapWidth=None, units="norm", color="black", pos=(-1.0, -0.5), anchorHoriz="left", anchorVert="bottom")

    for question in ordered_questions:
        event.clearEvents()  # avoid a stale keypress bleeding into this question's rating

        logger.log_row(**{
            "Timepoint": "ESQ",
            "Time": core.getTime() - experiment_start,
            "Experience Sampling Question": "{}_start".format(question["Label"]),
            "Task": "Experience Sampling Questions",
            "Task Iteration": "1",
            "Participant ID": participant_id,
            "Assoc Task": assoc_task,
        })

        rating_scale.noResponse = True
        start_pos = random.randrange(1, 10)
        rating_scale.markerStart = start_pos
        pos = start_pos
        increment = 0.1

        key_state = key.KeyStateHandler()
        win.winHandle.push_handlers(key_state)
        try:
            while rating_scale.noResponse:
                if key_state[key.LEFT]:
                    pos -= increment
                elif key_state[key.RIGHT]:
                    pos += increment
                pos = max(0, min(9, pos))

                rating_scale.setMarkerPos(pos)
                question_text.setText(question["Questions"])
                scale_high.setText(question["Scale_high"])
                scale_low.setText(question["Scale_low"])
                question_text.draw()
                scale_high.draw()
                scale_low.draw()
                rating_scale.draw()
                win.flip()
        finally:
            win.winHandle.remove_handlers(key_state)

        time.sleep(1)  # brief settle before the next question, matching the original's plain sleep
        response = rating_scale.getRating()

        logger.log_row(**{
            "Timepoint": "ESQ",
            "Time": core.getTime() - experiment_start,
            "Experience Sampling Question": "{}_response".format(question["Label"]),
            "Experience Sampling Response": response,
            "Task": "Experience Sampling Questions",
            "Task Iteration": "1",
            "Participant ID": participant_id,
            "Auxillary Data": "Marker Started at {}".format(start_pos + 1),
            "Assoc Task": assoc_task,
        })

if __name__ == "__main__":
    from psychopy import core, visual

    participant_id = "TEST001"
    session_id = "TEST"
    movie_id = "test_movie"
    seed = 12345

    data_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "test_data",
    )

    win = None
    logger = None

    try:
        questions = load_questions()
        instructions = load_instructions()

        win = visual.Window(
            size=(1280, 720),
            fullscr=False,
            color="white",
            units="norm",
        )

        logger = ESQLogger(
            data_dir=data_dir,
            participant_id=participant_id,
            session_id=session_id,
            seed=seed,
        )

        experiment_start = core.getTime()

        show_instructions(win, instructions)

        run_esq(
            win=win,
            participant_id=participant_id,
            movie_id=movie_id,
            questions=questions,
            logger=logger,
            experiment_start=experiment_start,
        )

        completion_text = visual.TextStim(
            win,
            text="ESQ test complete.\n\nPress Enter to close.",
            color="black",
            units="norm",
        )
        completion_text.draw()
        win.flip()

        event.waitKeys(keyList=["return"])

    finally:
        if logger is not None:
            logger.close()

        if win is not None:
            win.close()

        core.quit()