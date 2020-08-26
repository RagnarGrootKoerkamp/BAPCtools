#!/usr/bin/env python3
import re
import sys
from pathlib import Path


def strip_newline(s):
    if s.endswith('\n'):
        return s[:-1]
    else:
        return s


def crop_output(output):
    if len(output) > 200:
        output = output[:200]
        output += ' ...'
    return output


def _quick_diff(out, ans):
    if ans.count('\n') <= 1 and out.count('\n') <= 1:
        return crop_output('Got ' + strip_newline(out) + ' wanted ' + strip_newline(ans))
    else:
        return ''


# return: (success, message)
def default_output_validator(ans_path, feedback_dir, settings):
    # settings: floatabs, floatrel, case_sensitive, space_change_sensitive
    try:
        out = sys.stdin.read()
    except UnicodeDecodeError:
        return (False, 'Team output is not valid utf-8.')
    ans = ans_path.read_text()

    if out == ans:
        return (True, '')

    if not settings.case_sensitive:
        # convert to lowercase...
        out = out.lower()
        ans = ans.lower()

        if out == ans:
            return (True, 'case')

    floatabs = settings.float_absolute_tolerance
    floatrel = settings.float_relative_tolerance

    if settings.space_change_sensitive and floatabs == 0 and floatrel == 0:
        return (False, _quick_diff(out, ans))

    if settings.space_change_sensitive:
        words1 = re.split(r'\b(\S+)\b', out)
        words2 = re.split(r'\b(\S+)\b', ans)
    else:
        words1 = re.split(r'[ \t\r\n]+', out)
        words2 = re.split(r'[ \t\r\n]+', ans)
        if len(words1) > 0 and words1[-1] == '':
            words1.pop()
        if len(words2) > 0 and words2[-1] == '':
            words2.pop()
        if len(words1) > 0 and words1[0] == '':
            words1.pop(0)
        if len(words2) > 0 and words2[0] == '':
            words2.pop(0)

    if words1 == words2:
        if not settings.space_change_sensitive:
            return (True, 'white space')
        else:
            print('Strings became equal after space sensitive splitting! Something is wrong!')
            assert False

    if len(words1) != len(words2):
        return (False, _quick_diff(out, ans))

    peakabserr = 0
    peakrelerr = 0
    for (w1, w2) in zip(words1, words2):
        if w1 != w2:
            try:
                f1 = float(w1)
                f2 = float(w2)
                abserr = abs(f1 - f2)
                relerr = abs(f1 - f2) / f2 if f2 != 0 else 1000
                peakabserr = max(peakabserr, abserr)
                peakrelerr = max(peakrelerr, relerr)
                if abserr > floatabs and relerr > floatrel:
                    return (False, _quick_diff(out, ans))
            except ValueError:
                return (False, _quick_diff(out, ans))

    return (True, f'float: abs {peakabserr:.2g} rel {peakrelerr:.2g}')


class Settings:
    pass


def main():
    #in_path = Path(sys.argv[1])
    ans_path = Path(sys.argv[2])
    feedback_dir = Path(sys.argv[3])

    settings = Settings()
    bool_flags = ['case_sensitive', 'space_change_sensitive']
    flags = ['float_relative_tolerance', 'float_absolute_tolerance', 'float_tolerance']
    for flag in bool_flags:
        setattr(settings, flag, False)
    for flag in flags:
        setattr(settings, flag, 0)

    args = sys.argv[4:]
    for i in range(len(args)):
        if args[i] in bool_flags: setattr(settings, args[i], True)
        if args[i] in flags: setattr(settings, args[i], float(args[i + 1]))

    if settings.float_tolerance != 0:
        assert settings.float_relative_tolerance == 0
        assert settings.float_absolute_tolerance == 0
        settings.float_relative_tolerance = settings.float_tolerance
        settings.float_absolute_tolerance = settings.float_tolerance

    ok, message = default_output_validator(ans_path, feedback_dir, settings)
    sys.stderr.write(message + '\n')
    if ok is True: return exit(42)
    return exit(43)


if __name__ == '__main__':
    main()
