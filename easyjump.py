import argparse
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import typing
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum


class Mode(Enum):
    MOUSE = 1
    XCOPY = 2


def parse_args():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--mode")
    arg_parser.add_argument("--smart-case")
    arg_parser.add_argument("--label-chars")
    arg_parser.add_argument("--label-attrs")
    arg_parser.add_argument("--text-attrs")
    arg_parser.add_argument("--print-command-only")
    arg_parser.add_argument("--key")
    arg_parser.add_argument("--cursor-pos")
    arg_parser.add_argument("--regions")
    arg_parser.add_argument("--copy-line")
    arg_parser.add_argument("--copy-word")

    class Args(argparse.Namespace):
        def __init__(self):
            self.mode = ""
            self.smart_case = ""
            self.label_chars = ""
            self.label_attrs = ""
            self.text_attrs = ""
            self.print_command_only = ""
            self.key = ""
            self.cursor_pos = ""
            self.regions = ""
            self.copy_line = ""
            self.copy_word = ""
            self.paste_after = ""

    args = arg_parser.parse_args(sys.argv[1:], namespace=Args())

    global MODE, SMART_CASE, LABEL_CHARS, LABEL_ATTRS, TEXT_ATTRS, TEXT_ATTRS, PRINT_COMMAND_ONLY, KEY, CURSOR_POS, REGIONS, COPY_LINE, COPY_WORD, PASTE_AFTER
    MODE = {
        "mouse": Mode.MOUSE,
        "xcopy": Mode.XCOPY,
    }[args.mode.lower() or "mouse"]
    SMART_CASE = (args.smart_case.lower() or "on") == "on"
    LABEL_CHARS = args.label_chars or "fjdkslaghrueiwoqptyvncmxzb1234567890"
    LABEL_ATTRS = args.label_attrs or "\033[1m\033[38;5;172m"
    TEXT_ATTRS = args.text_attrs or "\033[0m\033[38;5;237m"
    PRINT_COMMAND_ONLY = (
        args.print_command_only.lower() or "on"
    ) == "on"  # mouse mode only
    KEY = args.key
    CURSOR_POS = tuple(
        map(
            lambda x: int(x),
            [] if args.cursor_pos == "" else args.cursor_pos.split(",", 1),
        )
    )
    REGIONS = tuple(
        map(lambda x: int(x), [] if args.regions == "" else args.regions.split(","))
    )
    COPY_LINE = args.copy_line == 'on'
    COPY_WORD = args.copy_word == 'on'
    PASTE_AFTER = args.paste_after == 'on'


parse_args()


class Screen:
    _id: str
    _tty: str
    _width: int
    _height: int
    _cursor_x: int
    _cursor_y: int
    _history_size: int
    _in_copy_mode: bool
    _scroll_position: typing.Optional[int]
    _alternate_on: bool
    _alternate_allowed: bool
    _lines: typing.List["Line"]
    _snapshot: str

    def __init__(self):
        self._fill_info()
        if MODE == Mode.MOUSE:
            self._exit_copy_mode()
        self._lines = self._get_lines()
        if not self._alternate_allowed:
            self._snapshot = self._get_snapshot()

    def _send_keys(self, command: str):
        args = [
            "tmux",
            "send-keys",
            "-t",
            self._id,
            "-X",
            command,
        ]
        subprocess.run(
            args,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @contextmanager
    def label_positions(
        self, positions: typing.List["Position"], labels: typing.List[str]
    ):
        raw_with_labels = self._do_label_positions(positions, labels)
        if MODE == Mode.XCOPY:
            self._exit_copy_mode()
        if self._alternate_allowed:
            self._enter_alternate()
        self._update(raw_with_labels)
        try:
            yield
        finally:
            if self._alternate_allowed:
                self._leave_alternate()
            else:
                self._update(self._snapshot)

    def jump_to_position(self, position: "Position"):
        if MODE == MODE.XCOPY:
            self._xcopy_jump_to_position(position)
        elif MODE == MODE.MOUSE:
            self._mouse_jump_to_position(position)
        else:
            assert False

    def _xcopy_jump_to_position(self, position: "Position"):
        ok = self._enter_copy_mode()
        if not ok:
            return
        args = ["tmux", "send-keys", "-t", self._id, "-X", "top-line"]
        subprocess.run(
            args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if position.line_number >= 2:
            args = [
                "tmux",
                "send-keys",
                "-t",
                self._id,
                "-X",
                "-N",
                str(position.line_number - 1),
                "cursor-down",
            ]
            subprocess.run(
                args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        if self.lines[0].chars == "":
            # adapt to bug of tmux: cursor at end of line,
            line_length = len(self._lines[position.line_number - 1].chars)
            reverse_column_number = line_length - position.char_number + 1
            args = [
                "tmux",
                "send-keys",
                "-t",
                self._id,
                "-X",
                "-N",
                str(reverse_column_number),
                "cursor-left",
            ]
            subprocess.run(
                args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        else:
            # cursor at start of line
            if position.char_number >= 2:
                args = [
                    "tmux",
                    "send-keys",
                    "-t",
                    self._id,
                    "-X",
                    "-N",
                    str(position.char_number - 1),
                    "cursor-right",
                ]
                subprocess.run(
                    args,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        if COPY_LINE:
            self._send_keys('begin-selection')
            self._send_keys('end-of-line')
            self._send_keys('cursor-left')
            self._send_keys('copy-selection-and-cancel')
        elif COPY_WORD:
            self._send_keys('begin-selection')
            self._send_keys('next-word-end')
            self._send_keys('copy-selection-and-cancel')

        if PASTE_AFTER:
            self._send_keys('show-buffer')

    def _mouse_jump_to_position(self, position: "Position"):
        x = bytes((0x20 + position.column_number,))
        y = bytes((0x20 + position.line_number,))
        keys = b"\033[M " + x + y + b"\033[M#" + x + y
        keys_in_hex = keys.hex()
        args = [
            "tmux",
            "send-keys",
            "-t",
            self._id,
            "-H",
        ]
        args.extend(keys_in_hex[i : i + 2] for i in range(0, len(keys_in_hex), 2))
        if PRINT_COMMAND_ONLY:
            sys.stdout.write(shlex.join(args))
        else:
            subprocess.run(
                args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

    @property
    def cursor_pos(self) -> typing.Tuple[int, int]:
        if len(CURSOR_POS) == 2:
            return CURSOR_POS[0], CURSOR_POS[1]
        return self._cursor_x + 1, self._cursor_y + 1

    @property
    def lines(self) -> typing.List["Line"]:
        return self._lines

    def _fill_info(self):
        args = [
            "tmux",
            "display-message",
            "-p",
            "#{pane_id},#{pane_tty},#{pane_width},#{pane_height},#{cursor_x},#{cursor_y},#{history_size},#{scroll_position},#{alternate_on}",
        ]
        proc = subprocess.run(args, check=True, capture_output=True)
        results = proc.stdout.decode()[:-1].split(",")
        self._id = results[0]
        self._tty = results[1]
        self._width = int(results[2])
        self._height = int(results[3])
        self._cursor_x = int(results[4])
        self._cursor_y = int(results[5])
        self._history_size = int(results[6])
        self._in_copy_mode = results[7] != ""
        if self._in_copy_mode:
            self._scroll_position = int(results[7])
        else:
            self._scroll_position = None
        self._alternate_on = results[8] == "1"
        if self._alternate_on:
            self._alternate_allowed = False
        else:
            args = ["tmux", "show-option", "-gv", "alternate-screen"]
            proc = subprocess.run(args, check=True, capture_output=True)
            result = proc.stdout.decode()[:-1]
            self._alternate_allowed = result == "on"

    def _get_lines(self) -> typing.List["Line"]:
        args = ["tmux", "capture-pane", "-t", self._id]
        if self._in_copy_mode:
            start_line_number = -self._scroll_position
            end_line_number = start_line_number + self._height - 1
            args += ["-S", str(start_line_number), "-E", str(end_line_number)]
        args += ["-p"]
        proc = subprocess.run(args, check=True, capture_output=True)
        chars_list = proc.stdout.decode()[:-1].split("\n")
        lines: typing.List[Line] = []
        for i, chars in enumerate(chars_list):
            display_width = _calculate_display_width(chars)
            if i == len(chars_list) - 1:
                trailing_whitespaces = " " * (self._width - display_width)
            else:
                trailing_whitespaces = " " * (self._width - display_width) + "\r\n"
            line = Line(chars, trailing_whitespaces)
            lines.append(line)
        return lines

    def _get_snapshot(self) -> str:
        args = ["tmux", "capture-pane", "-t", self._id, "-e", "-p"]
        proc = subprocess.run(args, check=True, capture_output=True)
        snapshot = proc.stdout.decode()[:-1].replace("\n", "\r\n")
        return snapshot

    def _do_label_positions(
        self, positions: typing.List["Position"], labels: typing.List[str]
    ):
        temp: typing.List[str] = []
        for line in self._lines:
            temp.append(line.chars)
            temp.append(line.trailing_whitespaces)
        raw = "".join(temp)
        offset = 0
        segments: typing.List[str] = []
        for i, label in enumerate(labels):
            position = positions[i]
            if offset < position.offset:
                segment = TEXT_ATTRS + raw[offset : position.offset]
                segments.append(segment)
            segment = LABEL_ATTRS + label
            segments.append(segment)
            offset = position.offset + len(label)
        if offset < len(raw):
            segment = TEXT_ATTRS + raw[offset:]
            segments.append(segment)
        raw_with_labels = "".join(segments)
        return raw_with_labels

    def _exit_copy_mode(self):
        if not self._in_copy_mode:
            return
        args = ["tmux", "send-keys", "-t", self._id, "-X", "cancel"]
        subprocess.run(
            args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self._in_copy_mode = False

    def _enter_copy_mode(self) -> bool:
        if self._in_copy_mode:
            return True
        args = ["tmux", "copy-mode", "-t", self._id]
        subprocess.run(
            args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if self._scroll_position is not None:
            history_size = self._get_history_size()
            if history_size % 2 != self._history_size % 2:
                # adapt to bug of tmux
                self._scroll_position -= 1
            self._history_size = history_size
            if self._scroll_position > self._history_size:
                return False
            args = [
                "tmux",
                "send-keys",
                "-t",
                self._id,
                "-X",
                "goto-line",
                str(self._scroll_position),
            ]
            subprocess.run(
                args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        self._in_copy_mode = True
        return True

    def _get_history_size(self) -> int:
        args = ["tmux", "display-message", "-t", self._id, "-p", "#{history_size}"]
        proc = subprocess.run(args, check=True, capture_output=True)
        history_size = int(proc.stdout.decode()[:-1])
        return history_size

    def _enter_alternate(self):
        with open(self._tty, "a") as f:
            f.write("\033[?1049h")
        self._alternate_on = True

    def _leave_alternate(self):
        with open(self._tty, "a") as f:
            f.write("\033[?1049l")
        self._alternate_on = False

    def _update(self, raw: str):
        with open(self._tty, "a") as f:
            f.write("\033[2J\033[H\033[0m")
            f.write(raw)
            f.write("\033[{};{}H".format(self._cursor_y + 1, self._cursor_x + 1))
        if self._scroll_position is not None and not self._alternate_on:
            self._scroll_position += self._height  # raw.count("\n") + 1


@dataclass
class Line:
    chars: str
    trailing_whitespaces: str


@dataclass
class Position:
    line_number: int
    char_number: int
    column_number: int
    offset: int


def get_key() -> str:
    if len(KEY) == 2:
        return KEY
    return _get_chars("search for key", 2, None)


def get_label(label_length, candidate_labels: typing.List[str]) -> typing.Optional[str]:
    try:
        return _get_chars("goto label", label_length, candidate_labels)
    except ValueError:
        return None


def _get_chars(
    prompt: str,
    number_of_chars: int,
    expected_chars_list: typing.Optional[typing.List[str]],
) -> str:
    format = "{} ({} char"
    if number_of_chars >= 2:
        format += "s"
    format += "): {:_<" + str(number_of_chars) + "}"
    chars = ""
    for _ in range(number_of_chars):
        prompt_with_input = format.format(prompt, number_of_chars, chars)
        chars += _get_char(prompt_with_input)
        if expected_chars_list is not None:
            for expected_chars in expected_chars_list:
                if expected_chars.startswith(chars):
                    break
            else:
                raise ValueError()
    return chars


def _get_char(prompt: str) -> str:
    temp_dir_name = tempfile.mkdtemp()
    try:
        temp_file_name = os.path.join(temp_dir_name, "fifo")
        try:
            return _do_get_char(prompt, temp_file_name)
        finally:
            os.unlink(temp_file_name)
    finally:
        os.rmdir(temp_dir_name)


def _do_get_char(prompt: str, temp_file_name: str) -> str:
    os.mkfifo(temp_file_name)
    args = [
        "tmux",
        "command-prompt",
        "-1",
        "-p",
        prompt,
        'run-shell -b "tee >> {} << EOF\\n%%%\\nEOF"'.format(
            shlex.quote(temp_file_name)
        ),
    ]
    subprocess.run(args, check=True)

    def handler(signum, frame):
        raise TimeoutError()

    signal.signal(signal.SIGALRM, handler)
    signal.alarm(30)
    try:
        with open(temp_file_name, "r") as f:
            char = f.readline()[:-1]
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
    if char == "":
        raise SystemExit()
    return char


def search_for_key(lines: typing.List[Line], key: str) -> typing.List[Position]:
    lower_key = key.lower()
    line_offset = 0
    positions: typing.List[Position] = []
    for line_index, line in enumerate(lines):
        lower_line_chars = line.chars.lower()
        char_index = -len(key)
        while True:
            char_index = lower_line_chars.find(lower_key, char_index + len(key))
            if char_index < 0:
                break
            potential_key = line.chars[char_index : char_index + len(key)]
            if not _test_potential_key(potential_key, key):
                continue
            column_index = _calculate_display_width(line.chars[:char_index])
            if not _point_is_in_region(column_index + 1, line_index + 1):
                continue
            offset = line_offset + char_index
            position = Position(
                line_index + 1, char_index + 1, column_index + 1, offset
            )
            positions.append(position)
        line_offset += len(line.chars) + len(line.trailing_whitespaces)
    return positions


def _calculate_display_width(s: str) -> int:
    display_width = 0
    for c in s:
        if unicodedata.east_asian_width(c) == "W":
            display_width += 2
        else:
            display_width += 1
    return display_width


def _test_potential_key(potential_key: str, key: str) -> bool:
    if potential_key == key:
        return True
    if not SMART_CASE:
        return False
    for c in key:
        if c.isupper():
            return False
    return True


def _point_is_in_region(x: int, y: int) -> bool:
    n = len(REGIONS)
    if n == 0:
        return True
    for i in range(0, n, 4):
        region = REGIONS[i : i + 4]
        if x >= region[0] and y >= region[1] and x <= region[2] and y <= region[3]:
            return True
    return False


def generate_labels(
    key_length: int, number_of_positions: int
) -> typing.Tuple[typing.List[str], int]:
    label_length = 1
    while len(LABEL_CHARS) ** label_length < number_of_positions:
        if label_length == min(key_length, len(LABEL_CHARS)):
            break
        label_length += 1
    labels: typing.List[str] = []

    def do_generate_labels(label_prefix) -> bool:
        if len(label_prefix) == label_length - 1:
            for label_char in LABEL_CHARS:
                if len(labels) == number_of_positions:
                    return True
                label = label_prefix + label_char
                labels.append(label)
        else:
            for label_char in LABEL_CHARS:
                stop = do_generate_labels(label_prefix + label_char)
                if stop:
                    return True
        return False

    do_generate_labels("")
    return labels, label_length


def sort_labels(
    labels: typing.List[str],
    positions: typing.List[Position],
    cursor_pos: typing.Tuple[int, int],
):
    def distance_to_cursor(position: Position) -> float:
        a = position.column_number - cursor_pos[0]
        b = 2 * (position.line_number - cursor_pos[1])
        c = (a * a + b * b) ** 0.5
        return c

    rank_2_position_idx = list(range(len(labels)))
    rank_2_position_idx.sort(key=lambda i: distance_to_cursor(positions[i]))
    sorted_labels = [""] * len(labels)
    for rank, position_idx in enumerate(rank_2_position_idx):
        sorted_labels[position_idx] = labels[rank]
    labels[:] = sorted_labels


def find_label(
    label: str, labels: typing.List[str], positions: typing.List[Position]
) -> typing.Optional[Position]:
    for i, label2 in enumerate(labels):
        if label == label2:
            position = positions[i]
            return position
    return None


def main():
    screen = Screen()
    key = get_key()
    positions = search_for_key(screen.lines, key)
    if len(positions) == 0:
        return
    if len(positions) == 1:
        position = positions[0]
        screen.jump_to_position(position)
        return
    labels, label_length = generate_labels(len(key), len(positions))
    sort_labels(labels, positions, screen.cursor_pos)
    with screen.label_positions(positions, labels):
        label = get_label(label_length, labels)
    if label is None:
        return
    position = find_label(label, labels, positions)
    if position is None:
        return
    screen.jump_to_position(position)


try:
    main()
except KeyboardInterrupt:
    pass
