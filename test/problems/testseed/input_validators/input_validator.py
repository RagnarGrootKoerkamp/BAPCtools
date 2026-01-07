#!/usr/bin/env python3
import hashlib
import re
import shlex
import sys

# Parse arguments of the validator
random_salt = sys.argv[1]
command_string = sys.argv[2]
count_indices = [None]
if 3 < len(sys.argv):
    count_indices = list(range(int(sys.argv[3])))
    # TODO handle a..=b
    # TODO handle [a, b, c]


# emulate bt generate of stdout.py <command_string>
def generate(random_salt, command_string, count_index):
    # 1. inject the count
    if "{count}" in command_string:
        command_string = command_string.replace("{count}", f"{count_index + 1}")

    def hash_string(string):
        sha = hashlib.sha512(usedforsecurity=False)
        sha.update(string.encode())
        return sha.hexdigest()

    # 2. get the seed value
    seed_value = random_salt
    if count_index is not None and count_index > 0:
        seed_value += f":{count_index}"
    seed_value += command_string.strip()
    seed = int(hash_string(seed_value), 16) % 2**31

    # 3. build the argv for stdout.py
    argv = shlex.split(command_string)

    # 4. inject the seed
    SEED_REGEX = re.compile(r"\{seed(:[0-9]+)?\}")
    argv = [SEED_REGEX.sub(str(seed), arg) for arg in argv]

    # 5. emulate stdout.py
    return f"{' '.join(argv[1:])}\n"


expected = [generate(random_salt, command_string, x) for x in count_indices]
got = sys.stdin.read()
if got not in expected:
    print(*expected)
    sys.exit(43)
else:
    sys.exit(42)
