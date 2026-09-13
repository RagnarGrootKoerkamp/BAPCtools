from pathlib import Path

from bapctools import config, util


def test_config_args_order():
    keys = config.args._known_keys
    for a, b in zip(keys, keys[1:]):
        assert a < b, f"{a} >= {b}"


def test_warnings():
    count = config.n_warn
    with config.suppress_warnings():
        util.warn("):")
    assert count == config.n_warn

    with config.temporary_args():
        config.args.ignore_warning = ["):"]
        util.warn("):")
    assert count == config.n_warn

    util.warn(":)")
    assert count < config.n_warn


def test_drop_suffix():
    assert util.drop_suffix(Path("a.b.c.d.e.f"), [".x", ".d.e.f", ".y"]) == Path("a.b.c")


def test_math_eval():
    assert util.math_eval("2+3") == 5
    assert util.math_eval("1==1") is None
    assert util.math_eval("(-1)**0.5") is None
    assert util.math_eval("()") is None
    assert util.math_eval("True") is None
    assert util.math_eval("1/0") is None
    assert util.math_eval("a+b") is None
    assert util.math_eval("test") is None
    assert util.math_eval("config.n_error") is None
    assert util.math_eval("...") is None
    assert util.math_eval("2.0") == 2.0
    assert util.math_eval("2,0") == 2.0
    assert util.math_eval("12,345,678") == 12345678
    assert util.math_eval("12,345,678.0") == 12345678.0
    assert util.math_eval("12.345.678") == 12345678
    assert util.math_eval("12.345.678,0") == 12345678.0
    assert util.math_eval("1e10") == 1e10
    assert util.math_eval("(2+2)*4/2") == (2 + 2) * 4 / 2


def test_crop_line():
    for s in ["abc", "abcdefg", "abc\ndefg", "abcdefg\n"]:
        assert len(util.crop_line(s, 5)) <= 5


def test_inc_label():
    assert util.inc_label("A") == "B"
    assert util.inc_label("Z") == "AA"
    assert util.inc_label("EZ") == "FA"
    assert util.inc_label("ZZZZZ") == "AAAAAA"
    assert util.inc_label("YZZZZZ") == "ZAAAAA"
    assert util.inc_label("ZZZZZY") == "ZZZZZZ"
