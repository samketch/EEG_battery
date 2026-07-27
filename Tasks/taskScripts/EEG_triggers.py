"""LSL trigger-marker sender for Neuroelectrics NIC2.

NIC2 must have its "LSL Label" marker setting configured to exactly match
STREAM_NAME below (case-sensitive), and the outlet created here must exist
*before* NIC2's recording/protocol is started, or NIC2 will never find it.
See mainscript.py for where connect() is called (early, before the
participant-facing task starts) and movieTask_EEG.run_movie_task for how
the four marker codes (movie start/end, ESQ start/end) are used.
"""
from pylsl import StreamInfo, StreamOutlet

STREAM_NAME = "MovieTaskTriggers"


class NicTriggerSender:
    """Best-effort sender of instantaneous integer trigger markers to NIC2 via LSL.

    Outlet-creation/send failures are logged once and swallowed rather than
    raised, so a missing/misconfigured NIC2 instance doesn't stop the
    behavioral task (e.g. when piloting without EEG hardware connected).
    """

    MOVIE_START = 1
    MOVIE_END = 2
    ESQ_START = 3
    ESQ_END = 4

    def __init__(self, stream_name=STREAM_NAME):
        self.stream_name = stream_name
        self._outlet = None
        self._warned = False

    def connect(self):
        """Creates the LSL marker outlet. Must be called before NIC2's recording/protocol starts."""
        try:
            info = StreamInfo(
                name=self.stream_name, type="Markers", channel_count=1,
                nominal_srate=0, channel_format="int32", source_id="movie_task_triggers",
            )
            self._outlet = StreamOutlet(info)
            print("LSL marker stream '{}' is live.".format(self.stream_name))
        except Exception as exc:
            print("WARNING: Could not create LSL outlet '{}' ({}). Continuing without EEG triggers.".format(
                self.stream_name, exc))
            self._outlet = None

    def send_trigger(self, code):
        """Pushes a single instantaneous integer marker sample."""
        if self._outlet is None:
            if not self._warned:
                print("WARNING: No LSL outlet; trigger {} not sent (further trigger warnings suppressed).".format(code))
                self._warned = True
            return
        try:
            self._outlet.push_sample([code])
        except Exception as exc:
            print("WARNING: Failed to push LSL trigger {}: {}. Disabling further triggers.".format(code, exc))
            self._outlet = None

    def close(self):
        """Releases the LSL outlet (pylsl tears it down when garbage-collected)."""
        self._outlet = None
