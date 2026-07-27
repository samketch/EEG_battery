"""Entry point for the simplified EEG movie-watching task.

Flow: collect participant info -> show intro screens -> hand off to
movieTask_EEG, which plays fixation crosses and movie clips back-to-back
with no participant input. See taskScripts/movieTask_EEG.py for the
fixation/playback/logging logic.
"""
import os
import random
import re
import sys

from psychopy import core, event, gui, visual

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
os.chdir(SCRIPT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from taskScripts import movieTask_EEG

MOVIE_DIR = os.path.join(SCRIPT_DIR, "taskScripts", "resources", "Movie_Task", "videos")
INTRO_TEXT_PATH = os.path.join(SCRIPT_DIR, "taskScripts", "resources", "group_inst", "movie_main.txt")
DATA_DIR = os.path.join(SCRIPT_DIR, "data")

# Every clip that must be shown to each participant, exactly once.
MOVIE_FILENAMES = [
    "lms.mp4",
    "12_years.mp4",
    "500Days.mp4",
    "backToFuture.mp4",
    "c4.mp4",
    "prestige.mp4",
    "pulpFiction.mp4",
    "shawshank.mp4",
]

PRE_FIRST_FIXATION_SEC = 5.0
BETWEEN_CLIPS_FIXATION_SEC = 10.0

PARTICIPANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def get_participant_info():
    """Show a GUI dialog to collect participant ID and experiment seed.

    Re-prompts until a non-empty, filesystem-safe participant ID is given.
    The seed defaults to a random value but can be overridden to reproduce
    a specific participant's movie order.
    """
    while True:
        info = {"Participant ID": "", "Experiment Seed": random.randint(1, 9_999_999)}
        dlg = gui.DlgFromDict(info, title="EEG Movie Task", order=["Participant ID", "Experiment Seed"])
        if not dlg.OK:
            core.quit()

        participant_id = str(info["Participant ID"]).strip()
        if not participant_id:
            print("Participant ID cannot be empty. Please try again.")
            continue
        if not PARTICIPANT_ID_PATTERN.match(participant_id):
            print("Participant ID may only contain letters, numbers, '-' and '_'. Please try again.")
            continue

        try:
            seed = int(info["Experiment Seed"])
        except (TypeError, ValueError):
            print("Experiment Seed must be an integer. Please try again.")
            continue

        return participant_id, seed


def build_movie_order(seed):
    """Deterministically shuffle the movie list from the experiment seed.

    Using a seeded, task-local Random instance (rather than the global
    `random` module) means this ordering can't accidentally be perturbed
    by unrelated calls to random elsewhere, and is fully reproducible from
    the seed alone.
    """
    rng = random.Random(seed)
    order = MOVIE_FILENAMES.copy()
    rng.shuffle(order)
    return order


def verify_movies_exist(order):
    missing = [name for name in order if not os.path.isfile(os.path.join(MOVIE_DIR, name))]
    if missing:
        raise FileNotFoundError(
            "Missing movie file(s) in {}: {}".format(MOVIE_DIR, ", ".join(missing))
        )


def load_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        raise RuntimeError("Could not read instructions file '{}': {}".format(path, exc)) from exc


def show_text_screen(win, text):
    stim = visual.TextStim(
        win, text=text, font="Arial", color="black", colorSpace="rgb",
        wrapWidth=1300, units="pix", height=32, anchorHoriz="center", anchorVert="center",
    )
    stim.draw()
    win.flip()
    event.waitKeys(keyList=["return"])


def main():
    participant_id, seed = get_participant_info()
    movie_order = build_movie_order(seed)
    verify_movies_exist(movie_order)
    movie_intro_text = load_text_file(INTRO_TEXT_PATH)

    win = None
    try:
        win = visual.Window(size=(1440, 960), color="white", fullscr=True, units="pix")

        show_text_screen(
            win,
            "Welcome to our experiment.\n"
            "Please follow the instructions on-screen and notify the attending researcher if anything is unclear.\n"
            "We are thankful for your participation.\n"
            "Press <return/enter> to continue.",
        )
        show_text_screen(win, movie_intro_text)

        movieTask_EEG.run_movie_task(
            win=win,
            participant_id=participant_id,
            seed=seed,
            movie_filenames=movie_order,
            movie_dir=MOVIE_DIR,
            data_dir=DATA_DIR,
            pre_fixation_sec=PRE_FIRST_FIXATION_SEC,
            inter_fixation_sec=BETWEEN_CLIPS_FIXATION_SEC,
        )

        show_text_screen(
            win,
            "This is the end of the experiment.\n\n"
            "Please inform the attending researcher you have completed testing.\n\n"
            "Thank you for participating!",
        )
    except KeyboardInterrupt:
        print("Experiment aborted by experimenter.")
    except Exception as exc:
        print("ERROR: Experiment terminated unexpectedly: {}".format(exc))
    finally:
        if win is not None:
            win.close()
        core.quit()


if __name__ == "__main__":
    main()
