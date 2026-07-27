"""Diagnostic tool: check whether NIC2 trigger markers actually landed in a
recorded .easy file, and cross-reference them against this task's own
movie_events.csv / esq_log.csv timestamps.

The .easy format is plain ASCII with one row per sample (2ms apart at
500 Hz), so scrolling for 32 marker events by hand across hundreds of
thousands of rows isn't practical -- this does it automatically.

Per Neuroelectrics documentation, markers are written in the second-to-last
column, and the last column is a per-sample Unix timestamp. This script
auto-detects the delimiter and the timestamp units (seconds vs
milliseconds), but the exact column layout isn't independently verified
against your NIC2 version -- if results look wrong, run with --peek first
to sanity-check the raw column values.

Usage:
    python check_easy_markers.py path/to/recording.easy
    python check_easy_markers.py path/to/recording.easy --events data/S001/S001_..._movie_events.csv
    python check_easy_markers.py path/to/recording.easy --peek
    python check_easy_markers.py path/to/recording.easy --annotate data/S001/S001_..._movie_log.csv
    python check_easy_markers.py path/to/recording.easy --annotate data/S001/S001_..._movie_log.csv --split-dir data/S001/clips
"""
import argparse
import csv
import glob
import os
from datetime import datetime

import pandas as pd

TOLERANCE_SEC = 1.0  # how far around each expected event time to search for a marker

# Must match taskScripts/EEG_triggers.py's NicTriggerSender code constants.
EXPECTED_MARKER_CODES = {
    "movie_start": 1,
    "movie_end": 2,
    "esq_start": 3,
    "esq_end": 4,
}


def parse_iso_timestamp(iso_str):
    """datetime.fromisoformat() needs Python 3.7+; the project targets 3.6."""
    return datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S.%f").timestamp()


def load_easy(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        first_line = f.readline()
    sep = "\t" if "\t" in first_line else r"\s+"
    df = pd.read_csv(path, sep=sep, header=None, engine="python")
    return df


def marker_and_timestamp_columns(df, marker_col=None, timestamp_col=None):
    if df.shape[1] < 2:
        raise ValueError("File only has {} column(s); can't locate a marker column.".format(df.shape[1]))
    if marker_col is None:
        marker_col = df.shape[1] - 2  # guess: penultimate column, per NE docs
    if timestamp_col is None:
        timestamp_col = df.shape[1] - 1  # guess: last column, per NE docs
    for name, col in (("marker", marker_col), ("timestamp", timestamp_col)):
        if col not in df.columns:
            raise ValueError("{} column {} is out of range (file has columns 0..{}).".format(
                name, col, df.shape[1] - 1))
    return marker_col, timestamp_col


def normalize_timestamps(raw_timestamps):
    """Returns timestamps as Unix seconds, auto-detecting seconds vs milliseconds."""
    sample = raw_timestamps.iloc[len(raw_timestamps) // 2]
    if sample > 1e12:  # looks like milliseconds (current epoch ms is ~1.7e12)
        return raw_timestamps / 1000.0
    return raw_timestamps


def find_closest_marker(df, marker_col, timestamps, expected_epoch, tolerance_sec, expected_code=None):
    """Returns (index, marker_value, offset_seconds) for the non-zero marker
    closest to expected_epoch within tolerance_sec, or None if there isn't
    one. If expected_code is given, only markers with that exact value are
    considered (use this when you need e.g. specifically a movie_start
    marker rather than whatever happens to be nearest in time).
    """
    marker_mask = df[marker_col] != 0
    if expected_code is not None:
        marker_mask = marker_mask & (df[marker_col] == expected_code)
    offsets = timestamps - expected_epoch
    nearby = marker_mask & (offsets.abs() <= tolerance_sec)
    if not nearby.any():
        return None
    closest_idx = offsets[nearby].abs().idxmin()
    return closest_idx, df.loc[closest_idx, marker_col], offsets.loc[closest_idx]


def find_easy_file(eeg_data_dir, participant_id):
    """Finds .easy file(s) for this participant in eeg_data_dir (NIC2's own
    recordings folder) and returns the most recently modified match, or None.
    """
    pattern = os.path.join(eeg_data_dir, "*{}*.easy".format(participant_id))
    candidates = glob.glob(pattern)
    if not candidates:
        return None
    candidates.sort(key=os.path.getmtime, reverse=True)
    for path in candidates:
        if path.endswith("edfFiltered.easy"):
            print("NOTE: ignoring {} (filtered output, not the raw recording)".format(path))
            candidates.remove(path)
    if not candidates:
        return None

    if len(candidates) > 1:
        print("NOTE: {} .easy file(s) matched participant '{}' in {}; using the most recently modified:".format(
            len(candidates), participant_id, eeg_data_dir))
        for path in candidates:
            print("  {} (modified {})".format(path, datetime.fromtimestamp(os.path.getmtime(path)).isoformat()))
    return candidates[0]


def annotate_movie_log_with_easy_indices(movie_log_path, easy_path, marker_col=None, timestamp_col=None,
                                          tolerance_sec=TOLERANCE_SEC):
    """Adds easy_file_start_index / easy_file_end_index columns to
    movie_log_path, giving the .easy file's row index where each clip's
    movie_start/movie_end marker was found (matched by expected code, not
    just proximity, so an ESQ marker landing closer in time can't be
    mistaken for the movie boundary). Overwrites movie_log_path in place.
    Returns the annotated DataFrame.
    """
    easy_df = load_easy(easy_path)
    marker_col, timestamp_col = marker_and_timestamp_columns(easy_df, marker_col, timestamp_col)
    timestamps = normalize_timestamps(easy_df[timestamp_col])

    movie_log = pd.read_csv(movie_log_path)
    start_indices, end_indices = [], []
    for _, row in movie_log.iterrows():
        label = "{} (order {})".format(row["movie_filename"], row["presentation_order"])

        start_result = find_closest_marker(
            easy_df, marker_col, timestamps, parse_iso_timestamp(row["start_timestamp_iso"]),
            tolerance_sec, expected_code=EXPECTED_MARKER_CODES["movie_start"])
        end_result = find_closest_marker(
            easy_df, marker_col, timestamps, parse_iso_timestamp(row["end_timestamp_iso"]),
            tolerance_sec, expected_code=EXPECTED_MARKER_CODES["movie_end"])

        if start_result is None:
            print("WARNING: no movie_start marker found near {}'s logged start time.".format(label))
        if end_result is None:
            print("WARNING: no movie_end marker found near {}'s logged end time.".format(label))

        start_indices.append(start_result[0] if start_result else None)
        end_indices.append(end_result[0] if end_result else None)

    # Int64 (nullable) so missing matches stay blank instead of becoming
    # float NaN/4969.0; float_format keeps the existing float columns at the
    # same 6-decimal precision MovieLogger wrote them with, rather than
    # picking up binary-float repr noise (e.g. 10.044808999999999) from the
    # pandas round-trip.
    movie_log["easy_file_start_index"] = pd.array(start_indices, dtype="Int64")
    movie_log["easy_file_end_index"] = pd.array(end_indices, dtype="Int64")
    movie_log.to_csv(movie_log_path, index=False, float_format="%.6f")
    print("Annotated {} with easy_file_start_index / easy_file_end_index.".format(movie_log_path))
    return movie_log


def split_easy_by_clip(movie_log_path, easy_path, output_dir):
    """Writes one .easy file per clip: the original file's raw text lines
    from easy_file_start_index through easy_file_end_index (inclusive),
    i.e. movie_start through movie_end -- ESQ is not included. Slices the
    ORIGINAL lines directly (rather than re-serializing through pandas) so
    there's no risk of reformatting/precision drift from the source file.
    Requires movie_log_path to already have easy_file_start_index /
    easy_file_end_index (run annotate_movie_log_with_easy_indices first).
    Returns the list of files written.
    """
    movie_log = pd.read_csv(movie_log_path)
    if "easy_file_start_index" not in movie_log.columns or "easy_file_end_index" not in movie_log.columns:
        raise ValueError(
            "{} has no easy_file_start_index/easy_file_end_index columns -- "
            "run annotate_movie_log_with_easy_indices first.".format(movie_log_path)
        )

    # newline="" on both read and write disables Python's universal-newline
    # translation, which otherwise silently rewrites the source file's line
    # endings to the OS default (e.g. \n -> \r\n on Windows) -- exactly the
    # kind of drift this function exists to avoid.
    with open(easy_path, "r", encoding="utf-8", errors="replace", newline="") as f:
        lines = f.readlines()

    os.makedirs(output_dir, exist_ok=True)
    written = []
    for _, row in movie_log.iterrows():
        label = "{} (order {})".format(row["movie_filename"], row["presentation_order"])
        start_idx, end_idx = row["easy_file_start_index"], row["easy_file_end_index"]
        if pd.isna(start_idx) or pd.isna(end_idx):
            print("Skipping {}: missing easy_file_start_index/easy_file_end_index.".format(label))
            continue

        start_idx, end_idx = int(start_idx), int(end_idx)
        clip_lines = lines[start_idx:end_idx + 1]  # inclusive of the movie_end row

        out_name = "{}_order{}_{}.easy".format(row["participant_id"], row["presentation_order"], row["movie_id"])
        out_path = os.path.join(output_dir, out_name)
        with open(out_path, "w", encoding="utf-8", newline="") as out_f:
            out_f.writelines(clip_lines)
        written.append(out_path)
        print("Wrote {} ({} rows, samples {}-{})".format(out_path, len(clip_lines), start_idx, end_idx))
    return written


def report_all_markers(df, marker_col, timestamp_col):
    marker_rows = df[df[marker_col] != 0]
    if marker_rows.empty:
        print("No non-zero values found in column {} (marker column guess).".format(marker_col))
        return
    print("Found {} non-zero marker sample(s) in column {}:".format(len(marker_rows), marker_col))
    for idx, row in marker_rows.iterrows():
        ts = datetime.fromtimestamp(normalize_timestamps(pd.Series([row[timestamp_col]])).iloc[0])
        print("  sample #{:>8} | marker={} | wall clock ~{}".format(idx, row[marker_col], ts.isoformat(timespec="milliseconds")))


def cross_reference(df, marker_col, timestamp_col, events_path):
    timestamps = normalize_timestamps(df[timestamp_col])

    print("\nCross-referencing against {}".format(events_path))
    print("(matching each expected event to its single closest marker, within +/- {}s)\n".format(TOLERANCE_SEC))

    with open(events_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("No rows in events file.")
        return

    hits, mismatches, misses = 0, 0, 0
    for row in rows:
        expected_epoch = parse_iso_timestamp(row["timestamp_iso"])
        expected_code = EXPECTED_MARKER_CODES.get(row["event"])
        label = "{} | {} (order {})".format(row["event"], row["movie_filename"], row["presentation_order"])

        # Closest marker of ANY code (not restricted to expected_code) so a
        # wrong-code marker shows up as a MISMATCH rather than being ignored.
        result = find_closest_marker(df, marker_col, timestamps, expected_epoch, TOLERANCE_SEC)
        if result is None:
            print("  MISSING  {:<50} no marker within +/- {}s of {}".format(label, TOLERANCE_SEC, row["timestamp_iso"]))
            misses += 1
            continue

        _, closest_value, closest_offset = result
        closest_offset_ms = closest_offset * 1000.0

        if expected_code is not None and closest_value != expected_code:
            print("  MISMATCH {:<50} closest marker={} ({:+.0f}ms) but expected code {}".format(
                label, closest_value, closest_offset_ms, expected_code))
            mismatches += 1
        else:
            print("  OK       {:<50} marker={} ({:+.0f}ms from expected time)".format(
                label, closest_value, closest_offset_ms))
            hits += 1

    print("\n{} OK, {} mismatched, {} missing out of {} expected events.".format(
        hits, mismatches, misses, len(rows)))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("easy_path", help="Path to the .easy recording file")
    parser.add_argument("--events", default=None, help="A movie_events.csv (or esq_log.csv) to cross-reference")
    parser.add_argument("--peek", action="store_true", help="Just print the first few rows/columns and exit")
    parser.add_argument("--marker-col", type=int, default=None,
                         help="0-indexed marker column, if you know it (default: guess penultimate column)")
    parser.add_argument("--timestamp-col", type=int, default=None,
                         help="0-indexed timestamp column, if you know it (default: guess last column)")
    parser.add_argument("--annotate", metavar="MOVIE_LOG_CSV", default=None,
                         help="Add easy_file_start_index/easy_file_end_index columns to this movie_log.csv")
    parser.add_argument("--split-dir", metavar="DIR", default=None,
                         help="With --annotate: also write one .easy file per clip into this directory")
    args = parser.parse_args()

    print("Loading {} ...".format(args.easy_path))
    df = load_easy(args.easy_path)
    print("Loaded {} rows, {} columns.\n".format(len(df), df.shape[1]))

    if args.peek:
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 200)
        print(df.head(10))
        return

    marker_col, timestamp_col = marker_and_timestamp_columns(df, args.marker_col, args.timestamp_col)
    print("Using marker column {}, timestamp column {}.\n".format(marker_col, timestamp_col))
    report_all_markers(df, marker_col, timestamp_col)

    if args.events:
        cross_reference(df, marker_col, timestamp_col, args.events)

    if args.annotate:
        annotate_movie_log_with_easy_indices(args.annotate, args.easy_path, marker_col, timestamp_col)
        if args.split_dir:
            split_easy_by_clip(args.annotate, args.easy_path, args.split_dir)


if __name__ == "__main__":
    main()
