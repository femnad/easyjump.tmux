#!/usr/bin/env python3
import dataclasses
import datetime
import os
import platform
import re
import shlex
import subprocess
import sys
import tempfile


@dataclasses.dataclass
class CommonOptions:
    # No boolean here as options are set to on if true
    smart_case: str
    label_chars: str
    label_attrs: str
    text_attrs: str
    auto_begin_selection: str
    copy_mode_bindings: str
    copy_mode_prefix: str


@dataclasses.dataclass
class ExtendedOptions:
    copy_word: bool = False
    copy_until_space: bool = False
    copy_line: bool = False
    paste_after: bool = True


def bind_keys(key_binding: str, common_options: CommonOptions, extended_options: ExtendedOptions):
    dir_name = os.path.dirname(os.path.abspath(__file__))
    script_file_name = os.path.join(dir_name, "easyjump.py")
    time_str = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S-%f")
    log_file_name = os.path.join(tempfile.gettempdir(), "easyjump_{}.log".format(time_str))

    shell_args = [
        sys.executable,
        script_file_name,
        "--mode",
        "xcopy",
        "--smart-case",
        common_options.smart_case,
        "--label-chars",
        common_options.label_chars,
        "--label-attrs",
        common_options.label_attrs,
        "--text-attrs",
        common_options.text_attrs,
        "--auto-begin-selection",
        common_options.auto_begin_selection,
    ]

    if extended_options.copy_word:
        shell_args.extend(['--copy-word', 'on'])
    elif extended_options.copy_until_space:
        shell_args.extend(['--copy-until-space', 'on'])
    elif extended_options.copy_line:
        shell_args.extend(['--copy-line', 'on'])
    if extended_options.paste_after:
        shell_args.extend(['--paste-after', 'on'])

    shell_command = shlex.join(shell_args)
    shell_args += " >>{} 2>&1 || true".format(shlex.quote(log_file_name))

    args = [
        "tmux",
        "bind-key",
        key_binding,
        "run-shell",
        "-b",
        shell_command,
    ]
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if common_options.copy_mode_bindings:
        return

    copy_mode_prefix = common_options.copy_mode_prefix
    copy_mode_key = f'{copy_mode_prefix}-{key_binding}' if copy_mode_prefix else key_binding

    args2 = args[:]
    args2[2:3] = ['-T', 'copy-mode', copy_mode_key]
    subprocess.run(args2, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    args3 = args[:]
    args3[2:3] = ['-T', 'copy-mode-vi', copy_mode_key]
    subprocess.run(args3, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def toggle_case(key: str) -> str:
    if key.isupper():
        return key.lower()
    return key.upper()


def bind_auxiliary_function(option_key: str, common_options: CommonOptions, extended_options: ExtendedOptions):
    key_binding = get_option(option_key)
    if key_binding == '':
        return

    bind_keys(key_binding, common_options, extended_options)

    # Flipped case binding for pasting after
    extended_options.paste_after = not extended_options.paste_after
    key_binding = toggle_case(key_binding)
    bind_keys(key_binding, common_options, extended_options)


def main() -> None:
    check_requirements()
    key_binding = get_option("@easyjump-key-binding")
    smart_case = get_option("@easyjump-smart-case")
    label_chars = get_option("@easyjump-label-chars")
    label_attrs = get_option("@easyjump-label-attrs")
    text_attrs = get_option("@easyjump-text-attrs")
    auto_begin_selection = get_option("@easyjump-auto-begin-selection")
    copy_mode_bindings = get_option("@easyjump-copy-mode-bindings")
    copy_mode_prefix = get_option("@easyjump-copy-mode-prefix")

    common_options = CommonOptions(smart_case=smart_case,
                                   label_chars=label_chars,
                                   label_attrs=label_attrs,
                                   text_attrs=text_attrs,
                                   auto_begin_selection=auto_begin_selection,
                                   copy_mode_bindings=copy_mode_bindings,
                                   copy_mode_prefix=copy_mode_prefix)

    # First bind the jump key
    jump_options = ExtendedOptions()
    bind_keys(key_binding, common_options, jump_options)

    # Bind the copy-word action
    copy_word_options = ExtendedOptions(copy_word=True)
    bind_auxiliary_function('@easyjump-copy-word-binding', common_options, copy_word_options)

    # Bind the copy-until-space action
    copy_until_space_options = ExtendedOptions(copy_until_space=True)
    bind_auxiliary_function('@easyjump-copy-until-space-binding', common_options, copy_until_space_options)

    # Bind the copy-line action
    copy_line_options = ExtendedOptions(copy_line=True)
    bind_auxiliary_function('@easyjump-copy-line-binding', common_options, copy_line_options)


def check_requirements() -> None:
    python_version = platform.python_version_tuple()
    if (int(python_version[0]), int(python_version[1])) < (3, 8):
        raise Exception("python version >= 3.8 required")

    proc = subprocess.run(("tmux", "-V"), check=True, capture_output=True)
    result = proc.stdout.decode()[:-1]
    if m := re.compile(r"^tmux (next-)?(\d+\.\d+)").match(result):
        tmux_version = float(m.group(2))
        if tmux_version < 3.0:
            raise Exception("tmux version >= 3.0 required")


def get_option(option_name: str) -> str:
    args = ["tmux", "show-option", "-gqv", option_name]
    proc = subprocess.run(args, check=True, capture_output=True)
    option_value = proc.stdout.decode()[:-1]
    return option_value


main()
