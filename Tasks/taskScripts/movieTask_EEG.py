"""Movie-watching task: fixation crosses, sequential clip playback, and an
Experience Sampling Questionnaire (ESQ) after each clip.

Once run_movie_task() starts, the only participant input is answering the
ESQ questions after each clip via its 1-10 rating scale; no input is
required during fixation or movie playback. Escape lets the experimenter
abort the session cleanly during fixation/playback -- see ESQ.run_esq for
why the same abort check isn't used during the questionnaire itself.

EEG trigger markers are sent to NIC2 (via LSL) for four events per clip:
movie_start, movie_end, esq_start, esq_end. The trigger_sender passed in
must already be connected -- see mainscript.py, where it's connected early
(before intro screens) since NIC2 needs the LSL outlet to exist before its
recording starts. If it's not reachable, a warning is printed once and the
task continues without triggers.
"""
import csv
import os
from datetime import datetime

import psychopy
psychopy.prefs.hardware["audioLib"] = ["sounddevice", "pyo", "pygame"]

from psychopy import core, event, visual
from psychopy.constants import FINISHED

from taskScripts import ESQ
from taskScripts.EEG_triggers import NicTriggerSender

MOVIE_SIZE = (1920, 1080)


def _now_iso():
    return datetime.now().isoformat(timespec="milliseconds")


def _check_experimenter_abort():
    if event.getKeys(keyList=["escape"]):
        raise KeyboardInterrupt("Experiment aborted by experimenter.")


def _show_fixation(win, duration_sec, cross):
    """Draws a fixation cross for exactly duration_sec, timed off a fresh clock."""
    clock = core.Clock()
    while clock.getTime() < duration_sec:
        cross.draw()
        win.flip()
        _check_experimenter_abort()


class MovieLogger:
    """Crash-safe CSV logging of movie onset/offset events for one participant session.

    Two files are written per session:
      - `*_movie_log.csv`: one row per clip (the main output), flushed as
        soon as that clip's offset is known.
      - `*_movie_events.csv`: one row per onset/offset event, flushed
        immediately when the event happens. This is the durable record if
        the program is interrupted mid-clip.
    """

    SUMMARY_FIELDS = [
        "participant_id", "movie_id", "movie_filename", "presentation_order",
        "condition", "random_seed",
        "start_timestamp_iso", "end_timestamp_iso",
        "start_time_experiment_seconds", "end_time_experiment_seconds",
        "duration_seconds",
    ]
    EVENT_FIELDS = [
        "participant_id", "movie_filename", "presentation_order", "event",
        "timestamp_iso", "time_experiment_seconds",
    ]

    def __init__(self, data_dir, participant_id, session_id, seed):
        participant_dir = os.path.join(data_dir, participant_id)
        os.makedirs(participant_dir, exist_ok=True)

        self.summary_path = os.path.join(
            participant_dir, "{}_{}_{}_movie_log.csv".format(participant_id, session_id, seed)
        )
        self.events_path = os.path.join(
            participant_dir, "{}_{}_{}_movie_events.csv".format(participant_id, session_id, seed)
        )

        # session_id has second resolution, so a collision here means two
        # sessions started in the same second -- refuse rather than overwrite.
        if os.path.exists(self.summary_path) or os.path.exists(self.events_path):
            raise FileExistsError(
                "Refusing to overwrite existing log for participant '{}': {}".format(
                    participant_id, self.summary_path
                )
            )

        self._summary_file = open(self.summary_path, "w", newline="", encoding="utf-8")
        self._events_file = open(self.events_path, "w", newline="", encoding="utf-8")
        self._summary_writer = csv.DictWriter(self._summary_file, fieldnames=self.SUMMARY_FIELDS)
        self._events_writer = csv.DictWriter(self._events_file, fieldnames=self.EVENT_FIELDS)
        self._summary_writer.writeheader()
        self._events_writer.writeheader()
        self._flush()

    def _flush(self):
        self._summary_file.flush()
        os.fsync(self._summary_file.fileno())
        self._events_file.flush()
        os.fsync(self._events_file.fileno())

    def log_event(self, participant_id, movie_filename, presentation_order, event_name, exp_time):
        self._events_writer.writerow({
            "participant_id": participant_id,
            "movie_filename": movie_filename,
            "presentation_order": presentation_order,
            "event": event_name,
            "timestamp_iso": _now_iso(),
            "time_experiment_seconds": "{:.6f}".format(exp_time),
        })
        self._flush()

    def log_summary_row(self, row):
        self._summary_writer.writerow(row)
        self._flush()

    def close(self):
        self._summary_file.close()
        self._events_file.close()


def run_movie_task(win, participant_id, seed, movie_filenames, movie_dir, data_dir,
                    pre_fixation_sec, inter_fixation_sec, esq_questions, esq_instructions,
                    trigger_sender, condition=None):
    """Plays each clip in movie_filenames (already in presentation order),
    followed immediately by an ESQ block after each clip.

    Each clip is preceded by a fixation cross: `pre_fixation_sec` before the
    first clip, `inter_fixation_sec` before every clip after that. Movie
    onset is logged at the screen refresh that first displays the clip;
    offset is logged at the refresh where MovieStim reports playback
    finished. `esq_questions`/`esq_instructions` come from ESQ.load_questions()/
    load_instructions(), loaded once up front so a bad ESQ file fails fast.
    `trigger_sender` is an already-connected EEG_triggers.NicTriggerSender;
    its lifecycle (connect/close) is owned by the caller.

    Returns the path to the movie_log.csv this session just wrote, for any
    post-processing keyed on it (e.g. check_easy_markers.py).
    """
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = MovieLogger(data_dir, participant_id, session_id, seed)
    esq_logger = ESQ.ESQLogger(data_dir, participant_id, session_id, seed)

    experiment_start = core.getTime()  # PsychoPy's monotonic clock reference
    cross = visual.TextStim(win, text="+", color="black", height=60, units="pix")

    try:
        for order_index, movie_filename in enumerate(movie_filenames, start=1):
            movie_path = os.path.join(movie_dir, movie_filename)
            if not os.path.isfile(movie_path):
                raise FileNotFoundError("Movie file not found: {}".format(movie_path))

            fixation_duration = pre_fixation_sec if order_index == 1 else inter_fixation_sec
            _show_fixation(win, fixation_duration, cross)

            try:
                mov = visual.MovieStim3(win, movie_path, size=MOVIE_SIZE, loop=False)
            except Exception as exc:
                raise RuntimeError("Failed to load movie '{}': {}".format(movie_filename, exc)) from exc

            # Onset: timestamp the screen refresh that first shows the clip,
            # then fire the trigger immediately after so it doesn't delay the flip.
            mov.draw()
            onset_flip_time = win.flip()
            trigger_sender.send_trigger(NicTriggerSender.MOVIE_START)
            onset_exp_time = onset_flip_time - experiment_start
            onset_iso = _now_iso()
            logger.log_event(participant_id, movie_filename, order_index, "movie_start", onset_exp_time)

            last_flip_time = onset_flip_time
            try:
                while mov.status != FINISHED:
                    mov.draw()
                    last_flip_time = win.flip()
                    _check_experimenter_abort()
            finally:
                # Release decoder/audio resources whether playback finished
                # normally or was interrupted.
                mov.stop()

            # Offset: timestamp of the last refresh drawn before FINISHED was
            # observed. True offset precision is bounded by one frame
            # duration, since status is only checked once per frame.
            trigger_sender.send_trigger(NicTriggerSender.MOVIE_END)
            offset_exp_time = last_flip_time - experiment_start
            offset_iso = _now_iso()
            logger.log_event(participant_id, movie_filename, order_index, "movie_end", offset_exp_time)

            logger.log_summary_row({
                "participant_id": participant_id,
                "movie_id": os.path.splitext(movie_filename)[0],
                "movie_filename": movie_filename,
                "presentation_order": order_index,
                "condition": condition if condition is not None else "",
                "random_seed": seed,
                "start_timestamp_iso": onset_iso,
                "end_timestamp_iso": offset_iso,
                "start_time_experiment_seconds": "{:.6f}".format(onset_exp_time),
                "end_time_experiment_seconds": "{:.6f}".format(offset_exp_time),
                "duration_seconds": "{:.6f}".format(offset_exp_time - onset_exp_time),
            })

            # ESQ: once per clip, immediately after it ends. esq_start/esq_end
            # are logged into the same movie_events.csv as movie_start/movie_end
            # (same schema fits) so check_easy_markers.py can cross-reference
            # all four trigger types per clip, not just the movie ones.
            movie_id = os.path.splitext(movie_filename)[0]
            trigger_sender.send_trigger(NicTriggerSender.ESQ_START)
            logger.log_event(participant_id, movie_filename, order_index, "esq_start", core.getTime() - experiment_start)
            ESQ.show_instructions(win, esq_instructions)
            ESQ.run_esq(win, participant_id, movie_id, esq_questions, esq_logger, experiment_start)
            trigger_sender.send_trigger(NicTriggerSender.ESQ_END)
            logger.log_event(participant_id, movie_filename, order_index, "esq_end", core.getTime() - experiment_start)
    finally:
        esq_logger.close()
        logger.close()

    return logger.summary_path
