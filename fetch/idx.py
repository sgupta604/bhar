"""NOAA `.idx` parsing, anchored `TMP:2 m above ground` selection, and byte-range arithmetic.

Text in, records out. This module performs **no network and no file I/O** — the caller hands it
the `.idx` body it already downloaded, and gets back the one record it wants plus the HTTP `Range`
header that pulls exactly that GRIB message.

Three rules earn their own lines here, each bought with a real bug (spike F9 / F10):

1. **The needle is anchored with a leading colon.** `TMP:2 m above ground` also matches
   `APTMP:2 m above ground` — apparent temperature, a different variable, and message number one
   in NBM. The colon is the entire difference between a temperature and a heat index.
2. **Message numbers stay `str`.** NAM emits sub-messages numbered `284.1` / `284.2`; `int()` on
   those raises. Nor may numbering be derived from line position — sub-messages make the two
   diverge, so a `.idx`'s line N is not its message N.
3. **A range ends at the next STRICTLY GREATER start offset, minus one.** Sub-message pairs share
   a start byte, so "the next line" yields a zero-or-negative length range. The last message has
   no successor and gets an open-ended `bytes=S-`.

Index numbers are never constants in this module: the selection is read out of the `.idx` on every
call, because NBM's `TMP:2 m above ground` index moves with lead time.
"""

from __future__ import annotations

# Keys: msg:str  start:int  date:str  var:str  level:str  fcst:str  extra:str  raw:str
IdxRecord = dict

#: The anchored needle. The LEADING COLON is load-bearing (spike F9) — without it this also
#: matches `APTMP:2 m above ground`, silently returning apparent temperature.
NEEDLE = ":TMP:2 m above ground:"

#: Ensemble spread records repeat the same variable and level; they are not the forecast value.
ENS_SPREAD = "ens std dev"

#: `{msg}:{start}:d={YYYYMMDDHH}:{VAR}:{level}:{fcst}:{optional extra}` — the first six fields are
#: fixed, and everything after them is one `extra` blob (NBM probability lines carry colons there).
_FIXED_FIELDS = 6


def parse_idx(text: str) -> list[IdxRecord]:
    """Parse a NOAA `.idx` body into records, preserving each line verbatim in ``raw``.

    Message numbers are returned as ``str`` and read from the line itself, never from the line's
    position. Blank lines are skipped. A malformed line raises ``ValueError`` naming the line.
    """
    records: list[IdxRecord] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        raw = line.rstrip("\r")
        if not raw.strip():
            continue

        parts = raw.split(":", _FIXED_FIELDS)
        if len(parts) < _FIXED_FIELDS:
            raise ValueError(
                f"malformed .idx line {line_number}: expected at least {_FIXED_FIELDS} "
                f"colon-separated fields "
                f"('{{msg}}:{{start}}:d=YYYYMMDDHH:{{VAR}}:{{level}}:{{fcst}}:'), "
                f"got {len(parts)} in {raw!r}"
            )

        msg, start_text, date, var, level, fcst = parts[:_FIXED_FIELDS]
        extra = parts[_FIXED_FIELDS] if len(parts) > _FIXED_FIELDS else ""

        try:
            start = int(start_text)
        except ValueError as exc:
            raise ValueError(
                f"malformed .idx line {line_number}: byte offset {start_text!r} is not an "
                f"integer, in {raw!r}"
            ) from exc

        records.append(
            {
                "msg": msg,  # str, always — NAM sub-messages ('284.1') make int() raise
                "start": start,
                "date": date,
                "var": var,
                "level": level,
                "fcst": fcst,
                "extra": extra,
                "raw": raw,
            }
        )

    return records


def select_tmp_2m(records: list[IdxRecord]) -> IdxRecord:
    """Return the single 2 m temperature record, or raise.

    Matches the anchored :data:`NEEDLE` against the verbatim line and rejects any record whose
    line carries :data:`ENS_SPREAD`. Exactly one record must survive; zero or more than one is a
    hard failure (SPEC §3 / spike F9), never a "pick the first" situation.
    """
    hits = [r for r in records if NEEDLE in r["raw"] and ENS_SPREAD not in r["raw"]]

    if len(hits) != 1:
        found = ", ".join(f"msg {r['msg']!r} @ {r['start']}" for r in hits) or "none"
        raise ValueError(
            f"SPEC §3 / spike F9: the anchored needle {NEEDLE!r} (with {ENS_SPREAD!r} rejected) "
            f"must select exactly one record, but matched {len(hits)} of {len(records)} records "
            f"in this .idx; matches: {found}"
        )

    return hits[0]


def byte_range(records: list[IdxRecord], chosen: IdxRecord) -> tuple[int, int | None]:
    """Return ``(start, end)`` for ``chosen``, inclusive, as an HTTP byte range.

    ``end`` is the next **strictly greater** start offset minus one — not the next line's offset,
    because sub-message pairs share a start byte and would produce a zero-length range. When no
    record starts later (the final message in the file), ``end`` is ``None``: the range runs to
    end-of-file.
    """
    start = chosen["start"]
    later = [r["start"] for r in records if r["start"] > start]

    if not later:
        return start, None

    return start, min(later) - 1


def range_header(start: int, end: int | None) -> str:
    """Render an HTTP ``Range`` header value: ``bytes=S-E``, or ``bytes=S-`` when ``end`` is None."""
    if end is None:
        return f"bytes={start}-"
    return f"bytes={start}-{end}"
