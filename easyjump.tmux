#!/usr/bin/env python3
from collections import namedtuple
import datetime
import os
import shlex
import subprocess
import sys
from typing import List


CommonOptions = namedtuple('Options', ['smart_case', 'label_chars', 'label_attrs', 'text_attrs'])


def get_option(option_name: str) -> str:
    args = ["tmux", "show-option", "-gqv", option_name]
    proc = subprocess.run(args, check=True, capture_output=True)
    option_value = proc.stdout.decode()[:-1]
    return option_value


def bind_keys(common_options: CommonOptions, key_binding: str, copy_line: bool = False, copy_word: bool = False,
        copy_mode_bindings: bool = True, paste_after: bool = False):
    dir_name = os.path.dirname(os.path.abspath(__file__))
    script_file_name = os.path.join(dir_name, "easyjump.py")
    time_str = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S-%f")

    shell_args = [
        sys.executable,
        script_file_name,
        "--mode", "xcopy",
        "--smart-case", common_options.smart_case,
        "--label-chars", common_options.label_chars,
        "--label-attrs", common_options.label_attrs,
        "--text-attrs", common_options.text_attrs,
    ]
    if copy_line:
        shell_args.extend(['--copy-line', 'on'])
    elif copy_word:
        shell_args.extend(['--copy-word', 'on'])

    if paste_after:
        shell_args.extend(['--paste-after', 'on'])

    args = [
        "tmux",
        "bind-key",
        key_binding,
        "run-shell",
        "-b",
        shlex.join(shell_args),
    ]
    subprocess.run(
        args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    if not copy_mode_bindings:
        return

    args2 = args[:]
    args2[2:3] = ['-T', 'copy-mode', 'C-' + key_binding]
    subprocess.run(
        args2, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    args3 = args[:]
    args3[2:3] = ['-T', 'copy-mode-vi', 'C-' + key_binding]
    subprocess.run(
        args3, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

def main():
    key_binding = get_option("@easyjump-key-binding") or "j"
    copy_line_key_binding = get_option("@easyjump-copy-line-binding") or "J"
    copy_word_key_binding = get_option("@easyjump-copy-word-binding") or "C-j"

    smart_case = get_option("@easyjump-smart-case")
    label_chars = get_option("@easyjump-label-chars")
    label_attrs = get_option("@easyjump-label-attrs")
    text_attrs = get_option("@easyjump-text-attrs")
    copy_line = get_option("@easyjump-copy-line")

    common_options = CommonOptions(smart_case, label_chars, label_attrs, text_attrs)

    bind_keys(common_options, key_binding)
    bind_keys(common_options, copy_line_key_binding, copy_line=True, copy_mode_bindings=False, paste_after=True)
    bind_keys(common_options, copy_word_key_binding, copy_word=True, copy_mode_bindings=False, paste_after=True)


main()
