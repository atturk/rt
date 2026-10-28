import io
import re
import sys

from rt.core import log_stamp
from rt.core.log_stamp import StampedStream, stamp_std_streams

STAMP = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "


def test_every_line_starts_with_date_and_time():
    out = io.StringIO()
    stream = StampedStream(out)
    print("▶ job 1", file=stream)
    stream.write("parte ")
    stream.write("della stessa riga\nseconda\nterza")
    stream.write(" fine\n")
    lines = out.getvalue().splitlines()
    assert len(lines) == 4
    assert all(re.match(STAMP, line) for line in lines)
    assert lines[1].endswith("parte della stessa riga")
    assert lines[3].endswith("terza fine")
    assert len(re.findall(STAMP, out.getvalue())) == 4


def test_terminal_stays_as_it_is(monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True
    tty, log = Tty(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", tty)
    monkeypatch.setattr(sys, "stderr", log)
    stamp_std_streams()
    stamp_std_streams()
    assert sys.stdout is tty
    assert isinstance(sys.stderr, StampedStream)
    assert not isinstance(sys.stderr._stream, StampedStream)


def test_stamp_format(monkeypatch):
    monkeypatch.setattr(log_stamp.time, "time", lambda: 0.25)
    assert re.fullmatch(STAMP, log_stamp.stamp())
    assert log_stamp.stamp().endswith(".250 ")
