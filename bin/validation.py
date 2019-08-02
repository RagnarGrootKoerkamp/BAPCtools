import config
import os
import re
import util


def quick_diff(ans, out):
    ans = ans.decode()
    out = out.decode()
    if ans.count('\n') <= 1 and out.count('\n') <= 1:
        return 'Got ' + util.strip_newline(out) + ' wanted ' + util.strip_newline(ans)
    else:
        return ''


# return: (success, remark)
def default_output_validator(ansfile, outfile, settings):
    # settings: floatabs, floatrel, case_sensitive, space_change_sensitive
    with open(ansfile, 'rb') as f:
        indata1 = f.read()

    with open(outfile, 'rb') as f:
        indata2 = f.read()

    if indata1 == indata2:
        return (True, '')

    if not settings.case_sensitive:
        # convert to lowercase...
        data1 = indata1.lower()
        data2 = indata2.lower()

        if data1 == data2:
            return (True, 'case')
    else:
        data1 = indata1
        data2 = indata2

    if settings.space_change_sensitive and settings.floatabs == None and settings.floatrel == None:
        return (False, quick_diff(data1, data2))

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
            return (True, 'white space')
        else:
            print('Strings became equal after space sensitive splitting! Something is wrong!')
            exit()

    if settings.floatabs is None and settings.floatrel is None:
        return (False, quick_diff(data1, data2))

    if len(words1) != len(words2):
        return (False, quick_diff(data1, data2))

    peakabserr = 0
    peakrelerr = 0
    for (w1, w2) in zip(words1, words2):
        if w1 != w2:
            try:
                f1 = float(w1)
                f2 = float(w2)
                abserr = abs(f1 - f2)
                relerr = abs(f1 - f2) / f1
                peakabserr = max(peakabserr, abserr)
                peakrelerr = max(peakrelerr, relerr)
                if ((settings.floatabs is None or abserr > settings.floatabs)
                        and (settings.floatrel is None or relerr > settings.floatrel)):
                    return (False, quick_diff(data1, data2))
            except ValueError:
                return (False, quick_diff(data1, data2))

    return (True, 'float: abs {0:.2g} rel {1:.2g}'.format(peakabserr, peakrelerr))


# call output validators as ./validator in ans feedbackdir additional_arguments < out
# return (success, remark)
def custom_output_validator(testcase, outfile, settings, output_validators):
    flags = []
    if settings.space_change_sensitive:
        flags += ['space_change_sensitive']
    if settings.case_sensitive:
        flags += ['case_sensitive']

    for output_validator in output_validators:
        ret = None
        with open(outfile, 'rb') as outf:
            ret = util.exec_command(
                output_validator[1] +
                [testcase.with_suffix('.in'),
                 testcase.with_suffix('.ans'), config.tmpdir] + flags,
                expect=config.RTV_AC,
                stdin=outf)
        # Read judgemessage if present
        judgemessagepath = config.tmpdir / 'judgemessage.txt'
        judgemessage = ''
        if judgemessagepath.is_file():
            with judgemessagepath.open() as judgemessagefile:
                judgemessage = judgemessagefile.read()
            os.unlink(judgemessagepath)

        if ret[0] is True:
            continue
        if ret[0] == config.RTV_WA:
            return (False, ret[1] + judgemessage)
        print('ERROR in output validator ', output_validator[0], ' exit code ', ret[0], ': ',
              ret[1])
        exit(False)
    return (True, judgemessage)
