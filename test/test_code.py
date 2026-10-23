from pathlib import Path

from bapctools import bar, config, expectations, util


def test_config_args_order():
    keys = config.args._known_keys
    for a, b in zip(keys, keys[1:]):
        assert a < b, f"{a} >= {b}"


def test_warnings():
    count = config.n_warn
    with config.suppress_warnings():
        bar.warn("):")
    assert count == config.n_warn

    with config.temporary_args():
        config.args.ignore_warning = ["):"]
        bar.warn("):")
    assert count == config.n_warn

    bar.warn(":)")
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


def test_glob():
    cases = [
        # Parents
        ("a", "a", True),  # exact match
        ("A", "a", False),  # case sensitive
        ("a", "A", False),  # case sensitive
        ("a", "a/b", True),  # matches a parent
        ("a", "a/b.ext", True),  # matches a parent
        ("a/*", "a/b/c", True),  # matches a parent
        ("a/*", "a/b/c.ext", True),  # matches a parent
        ("a/*/d.ext", "a/b/c/d.ext", False),  # * does not match a/b
        ("a/*/*/d.ext", "a/b/c/d.ext", True),  # */* matches a/b
        ("a*/b", "a/b", True),  # * can match the empty string
        ("a/*.ext", "a/b.ext", True),  # * can match part of a string
        # Braces
        ("{a,b}", "a", True),
        ("{a,b}", "b", True),
        ("{a,b}", "c", False),
        ("{a,b}", "{a,b}", False),
        ("{a,}b", "b", True),
        ("{a,}b", "ab", True),
        ("{a,b/c}", "b/c", True),
        # Braces with *
        ("{a,*}", "b", True),
        ("{a,*}b", "c/b", False),
        # Nested braces
        ("{a,{b,c}}", "{a,b}", True),
        ("{a,{b,c}}", "{a,c}", True),
        ("{a,{b,c}}", "{a,{b,c}}", False),
        ("{a,{b,c}}", "a", False),
        # Literal matches
        ("a,b", "a,b", True),
        ("a,b", "a", False),
        ("a.c", "a.c", True),
        ("a.c", "abc", False),
        ("a+", "a+", True),
        ("a+", "aaa", False),
        ("ab?", "ab?", True),
        ("ab?", "a", False),
        ("[a]", "[a]", True),
        ("[a]", "a", False),
        ("(a|b)", "a", False),
        ("(a|b)", "(a|b)", True),
        ("%$)(][-#$+*?", "%$)(][-#$+*?", True),
    ]
    for glob, path, expected in cases:
        regex = expectations._compile_glob(glob)
        got = regex.match(path) is not None
        assert expected == got, f"{glob} {path} {expected}"
