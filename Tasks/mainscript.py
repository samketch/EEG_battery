"""Entry point for the simplified EEG movie-watching task.

Flow: collect participant info -> show intro screens -> hand off to
movieTask_EEG, which plays fixation crosses and movie clips back-to-back,
followed by an Experience Sampling Questionnaire (ESQ) after each clip. See
taskScripts/movieTask_EEG.py for the fixation/playback/ESQ/logging/trigger
logic.
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

import check_easy_markers
from taskScripts import ESQ, movieTask_EEG
from taskScripts.EEG_triggers import NicTriggerSender

INTRO_TEXT_PATH = os.path.join(SCRIPT_DIR, "taskScripts", "resources", "group_inst", "movie_main.txt")
DATA_DIR = os.path.join(SCRIPT_DIR, "data")

# Wherever NIC2 is configured to save its recordings -- used to auto-locate
# this session's .easy file for post-processing once the recording is done.
EEG_DATA_DIR = os.path.join(SCRIPT_DIR, "data", "EEG_data")

# Must exactly match (case-sensitive) the "LSL Label" configured in NIC2's
# marker settings.
LSL_STREAM_NAME = "MovieTaskTriggers"

# --- Test mode -----------------------------------------------------------
# TEST_MODE must be False for any real participant session. When True: runs
# windowed (not fullscreen) against a 3-clip subset of the real movies, with
# short fixations, purely so playback/logging/triggers can be iterated on
# quickly. Production behavior (fullscreen, all 8 clips, 30s/10s fixations)
# is untouched by this flag being True/False -- it's a switch, not a
# permanent change to the production values.
TEST_MODE = True

MOVIE_DIR = os.path.join(SCRIPT_DIR, "taskScripts", "resources", "Movie_Task", "videos")

# Every clip that must be shown to each participant, exactly once.
PRODUCTION_MOVIE_FILENAMES = [
    "lms.mp4",
    "12_years.mp4",
    "500Days.mp4",
    "backToFuture.mp4",
    "c4.mp4",
    "prestige.mp4",
    "pulpFiction.mp4",
    "shawshank.mp4",
]
# Smallest/fastest 3 of the real clips (by file size), for quick iteration
# without waiting through all 8.
TEST_MOVIE_FILENAMES = ["c4.mp4", "shawshank.mp4", "12_years.mp4"]

PRODUCTION_PRE_FIRST_FIXATION_SEC = 30.0
PRODUCTION_BETWEEN_CLIPS_FIXATION_SEC = 10.0
TEST_PRE_FIRST_FIXATION_SEC = 3.0
TEST_BETWEEN_CLIPS_FIXATION_SEC = 2.0

MOVIE_FILENAMES = TEST_MOVIE_FILENAMES if TEST_MODE else PRODUCTION_MOVIE_FILENAMES
PRE_FIRST_FIXATION_SEC = TEST_PRE_FIRST_FIXATION_SEC if TEST_MODE else PRODUCTION_PRE_FIRST_FIXATION_SEC
BETWEEN_CLIPS_FIXATION_SEC = TEST_BETWEEN_CLIPS_FIXATION_SEC if TEST_MODE else PRODUCTION_BETWEEN_CLIPS_FIXATION_SEC

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
    if TEST_MODE:
        print("*** TEST_MODE is True: 3-clip subset, windowed, short fixations. ***")
        print("*** Set TEST_MODE = False in mainscript.py before any real session. ***")

    participant_id, seed = get_participant_info()
    movie_order = build_movie_order(seed)
    verify_movies_exist(movie_order)
    movie_intro_text = load_text_file(INTRO_TEXT_PATH)
    esq_questions = ESQ.load_questions()
    esq_instructions = ESQ.load_instructions()

    # NIC2 only discovers the LSL marker stream if it already exists when
    # NIC2's recording/protocol is started, so this has to happen -- and the
    # experimenter has to start the recording -- before any participant-facing
    # screens appear.
    trigger_sender = NicTriggerSender(LSL_STREAM_NAME)
    trigger_sender.connect()
    #input("Start the NIC2 recording now, then press Enter here to begin the task...")

    win = None
    movie_log_path = None
    try:
        win = visual.Window(size=(1440, 960), color="white", fullscr=not TEST_MODE, units="pix")

        show_text_screen(
            win,
            "Welcome to our experiment.\n"
            "Please follow the instructions on-screen and notify the attending researcher if anything is unclear.\n"
            "We are thankful for your participation.\n"
            "Press <return/enter> to continue.",
        )
        show_text_screen(win, movie_intro_text)

        movie_log_path = movieTask_EEG.run_movie_task(
            win=win,
            participant_id=participant_id,
            seed=seed,
            movie_filenames=movie_order,
            movie_dir=MOVIE_DIR,
            data_dir=DATA_DIR,
            pre_fixation_sec=PRE_FIRST_FIXATION_SEC,
            inter_fixation_sec=BETWEEN_CLIPS_FIXATION_SEC,
            esq_questions=esq_questions,
            esq_instructions=esq_instructions,
            trigger_sender=trigger_sender,
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
        trigger_sender.close()

    # Post-processing only runs if the task actually completed (movie_log_path
    # was returned). It's best-effort: any failure here is a warning, not a
    # crash -- the session's real data (movie_log.csv, movie_events.csv,
    # esq_log.csv, and NIC2's own recording) is already safely saved
    # regardless of whether this extra step succeeds.
    if movie_log_path is not None:
        #input("Stop the NIC2 recording now, then press Enter to process the .easy file...")
        try:
            easy_path = check_easy_markers.find_easy_file(EEG_DATA_DIR, participant_id)
            if easy_path is None:
                print("WARNING: No .easy file found for participant '{}' in {}. Skipping post-processing; "
                      "you can run check_easy_markers.py manually once you locate it.".format(
                          participant_id, EEG_DATA_DIR))
            else:
                print("Found .easy file: {}".format(easy_path))
                check_easy_markers.annotate_movie_log_with_easy_indices(movie_log_path, easy_path)
                clips_dir = os.path.join(os.path.dirname(movie_log_path), "clips")
                check_easy_markers.split_easy_by_clip(movie_log_path, easy_path, clips_dir)
        except Exception as exc:
            print("WARNING: .easy post-processing failed: {}. Your experiment data is unaffected; "
                  "you can re-run check_easy_markers.py manually.".format(exc))

    core.quit()


if __name__ == "__main__":
    main()
