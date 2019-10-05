import config
import os
import re
import util


def quick_diff(ans, out):
    ans = ans.decode()
    out = out.decode()
    if ans.count('\n') <= 1 and out.count('\n') <= 1:
        return util.crop_output('Got ' + util.strip_newline(out) + ' wanted ' +
                util.strip_newline(ans))
    else:
        return ''


# return: (success, err, out=None)
def default_output_validator(ansfile, outfile, settings):
    # settings: floatabs, floatrel, case_sensitive, space_change_sensitive
    with open(ansfile, 'rb') as f:
        indata1 = f.read()

    with open(outfile, 'rb') as f:
        indata2 = f.read()

    if indata1 == indata2:
        return (True, '', None)

    if not settings.case_sensitive:
        # convert to lowercase...
        data1 = indata1.lower()
        data2 = indata2.lower()

        if data1 == data2:
            return (True, 'case', None)
    else:
        data1 = indata1
        data2 = indata2

    if settings.space_change_sensitive and settings.floatabs == None and settings.floatrel == None:
        return (False, quick_diff(data1, data2), None)

    if settings.space_change_sensitive:
        words1 = re.split(rb'\b(\S+)\b', data1)
        words2 = re.split(rb'\b(\S+)\b', data2)
    else:
        words1 = re.split(rb'[ \n]+', data1)
        words2 = re.split(rb'[ \n]+', data2)
        if len(words1) > 0 and words1[-1] == b'': words1.pop()
        if len(words2) > 0 and words2[-1] == b'': words2.pop()
        if len(words1) > 0 and words1[0] == b'': words1.pop(0)
        if len(words2) > 0 and words2[0] == b'': words2.pop(0)

    if words1 == words2:
        if not settings.space_change_sensitive:
            return (True, 'white space', None)
        else:
            print('Strings became equal after space sensitive splitting! Something is wrong!')
            exit()

    if settings.floatabs is None and settings.floatrel is None:
        return (False, quick_diff(data1, data2), None)

    if len(words1) != len(words2):
        return (False, quick_diff(data1, data2), None)

    peakabserr = 0
    peakrelerr = 0
    for (w1, w2) in zip(words1, words2):
        if w1 != w2:
            try:
                f1 = float(w1)
                f2 = float(w2)
                abserr = abs(f1 - f2)
                relerr = abs(f1 - f2) / f1 if f1 != 0 else 1000
                peakabserr = max(peakabserr, abserr)
                peakrelerr = max(peakrelerr, relerr)
                if ((settings.floatabs is None or abserr > settings.floatabs)
                        and (settings.floatrel is None or relerr > settings.floatrel)):
                    return (False, quick_diff(data1, data2), None)
            except ValueError:
                return (False, quick_diff(data1, data2), None)

    return (True, 'float: abs {0:.2g} rel {1:.2g}'.format(peakabserr, peakrelerr), None)


# call output validators as ./validator in ans feedbackdir additional_arguments < out
# return (success, err, out) for the last validator that was run.
def custom_output_validator(testcase, outfile, settings, output_validators):
    flags = []
    if settings.space_change_sensitive:
        flags += ['space_change_sensitive']
    if settings.case_sensitive:
        flags += ['case_sensitive']

    run_all_validators = hasattr(settings, 'all_validators') and settings.all_validators

    ok = None
    err = None
    out = None
    for output_validator in output_validators:
        header = output_validator[0] + ': ' if len(output_validators) > 1 else ''
        with open(outfile, 'rb') as outf:
            judgepath = config.tmpdir/'judge'
            judgepath.mkdir(parents=True, exist_ok=True)
            judgemessage = judgepath/'judgemessage.txt'
            judgeerror = judgepath/'judgeerror.txt'
            val_ok, err, out = util.exec_command(
                output_validator[1] +
                [testcase.with_suffix('.in'),
                 testcase.with_suffix('.ans'), judgepath] + flags,
                expect=config.RTV_AC,
                stdin=outf)
            if err is None: err = ''
            if judgemessage.is_file():
                err += judgemessage.read_text()
                judgemessage.unlink()
            if judgeerror.is_file():
                # Remove any std output because it will usually only contain the
                err = judgeerror.read_text()
                judgeerror.unlink()
            if err:
                err = header + err

        if ok == None: ok = val_ok
        if run_all_validators and val_ok != ok:
            ok = 'INCONSISTENT_VALIDATORS'
            err = 'INCONSISTENT VALIDATORS: ' + err
            return (ok, err, out)

        if val_ok is True: continue
        if not run_all_validators:
            break

    if ok == config.RTV_WA: ok = False
    return (ok, err, out)
