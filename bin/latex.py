# Subcommands for building problem pdfs from the latex source.

import os
import util
import re
import tempfile
import sys
from pathlib import Path
from colorama import Fore, Style

import config
import util
import generate
from util import *
from contest import *


def latex_builddir(problem, language):
    builddir = problem.tmpdir / 'latex' / language
    builddir.mkdir(parents=True, exist_ok=True)
    return builddir


def create_samples_file(problem, language):
    builddir = latex_builddir(problem, language)

    # create the samples.tex file
    # For samples, find all .in/.ans/.interaction pairs.
    samples = problem.statement_samples()
    if samples is False:
        samples = []

    samples_file_path = builddir / 'samples.tex'

    if samples is []:
        samples_file_path.write_text('')
        return

    def build_sample_command(content):
        return f'\\expandafter\\def\\csname Sample{i+1}\\endcsname{{{content}}}\n'

    samples_data = []
    fallback_call = []
    for i, sample in enumerate(samples):
        fallback_call.append(f'\t\\csname Sample{i+1}\\endcsname\n')

        current_sample = []
        if isinstance(sample, Path):
            assert sample.suffix == '.interaction'
            if problem.interactive:
                interaction_dir = builddir / 'interaction'
                interaction_dir.mkdir(exist_ok=True)

                current_sample.append('\\InteractiveSampleHeading\n')
                lines = sample.read_text()
                last = 'x'
                cur = ''

                interaction_id = 0
                pass_id = 1

                def flush():
                    assert last in '<>'
                    nonlocal current_sample, interaction_id

                    interaction_file = (
                        interaction_dir / f'{sample.with_suffix("").name}-{interaction_id:02}'
                    )
                    interaction_file.write_text(cur)

                    mode = 'InteractiveRead' if last == '<' else 'InteractiveWrite'
                    current_sample.append(f'\\{mode}{{{interaction_file.as_posix()}}}\n')
                    interaction_id += 1

                for line in lines.splitlines():
                    if line == '---':
                        pass_id += 1
                        flush()
                        last = 'x'
                        cur = ''
                        current_sample.append(f'\\InteractivePass{{{pass_id}}}')
                    elif line[0] == last:
                        cur += line[1:] + '\n'
                    else:
                        if cur:
                            flush()
                        cur = line[1:] + '\n'
                        last = line[0]
                flush()
            else:
                assert problem.multipass

                multipass_dir = builddir / 'multipass'
                multipass_dir.mkdir(exist_ok=True)

                lines = sample.read_text()
                last = '<'
                cur_in = ''
                cur_out = ''

                pass_id = 1

                def flush():
                    nonlocal current_sample

                    in_path = multipass_dir / f'{sample.with_suffix("").name}-{pass_id:02}.in'
                    out_path = multipass_dir / f'{sample.with_suffix("").name}-{pass_id:02}.out'
                    in_path.write_text(cur_in)
                    out_path.write_text(cur_out)

                    if pass_id == 1:
                        current_sample.append(
                            f'\\Sample{{{in_path.as_posix()}}}{{{out_path.as_posix()}}}\n'
                        )
                    else:
                        current_sample.append(f'\\SamplePass{{{pass_id}}}\n')
                        current_sample.append(
                            f'\\SampleNoHeading{{{in_path.as_posix()}}}{{{out_path.as_posix()}}}\n'
                        )

                for line in lines.splitlines():
                    if line == '---':
                        flush()
                        pass_id += 1
                        last = '<'
                        cur_in = ''
                        cur_out = ''
                    else:
                        if line[0] == '<':
                            assert last == '<'
                            cur_in += line[1:] + '\n'
                        else:
                            assert line[0] == '>'
                            cur_out += line[1:] + '\n'
                            last = '>'
                flush()
        else:
            (in_path, ans_path) = sample
            current_sample = [f'\\Sample{{{in_path.as_posix()}}}{{{ans_path.as_posix()}}}']
        samples_data.append(build_sample_command(''.join(current_sample)))

    # This is only for backwards compatibility in case other people use the generated samples.tex
    # but not the bapc.cls. If remainingsamples is implemented we expect that the class is up to
    # date and does not need the legacy fallback
    samples_data += [
        '% this is only for backwards compatibility\n',
        '\\ifcsname remainingsamples\\endcsname\\else\n',
        ''.join(fallback_call),
        '\\fi\n',
    ]

    samples_file_path.write_text(''.join(samples_data))


# Steps needed for both problem and contest compilation.
def prepare_problem(problem, language):
    create_samples_file(problem, language)


def get_tl(problem):
    problem_config = problem.settings
    tl = problem_config.timelimit
    tl = int(tl) if abs(tl - int(tl)) < 0.0001 else tl

    if 'print_timelimit' in contest_yaml():
        print_tl = contest_yaml()['print_timelimit']
    else:
        print_tl = not config.args.no_timelimit

    return tl if print_tl else ''


def make_environment():
    env = os.environ.copy()
    # Search the contest directory and the latex directory.
    latex_paths = [
        Path.cwd(),
        Path.cwd() / 'solve_stats',
        Path.cwd() / 'solve_stats' / 'activity',
        config.tools_root / 'latex',
    ]
    texinputs = ''
    for p in latex_paths:
        texinputs += str(p) + ';'
    if config.args.verbose >= 2:
        print(f"export TEXINPUTS='{texinputs}'", file=sys.stderr)
    if 'TEXINPUTS' in env:
        prev = env['TEXINPUTS']
        if len(prev) > 0 and prev[-1] != ';':
            prev += ';'
        texinputs = prev + texinputs
    env['TEXINPUTS'] = texinputs
    return env


def build_latex_pdf(builddir, tex_path, language, bar=None, problem_path=None):
    env = make_environment()

    if shutil.which('latexmk') == None:
        bar.fatal('latexmk not found!')

    logfile = (builddir / tex_path.name).with_suffix('.log')
    built_pdf = (builddir / tex_path.name).with_suffix('.pdf')
    output_pdf = Path(built_pdf.name).with_suffix(f'.{language}.pdf')
    dest_path = output_pdf if problem_path is None else problem_path / output_pdf

    latexmk_command = [
        'latexmk',
        '-cd',
        '-g',
        f'-usepretex="\\\\newcommand\\\\lang{{{language}}}"',
        '-pdf',
        # %P passes the pretex to pdflatex.
        # %O makes sure other default options (like the working directory) are passed correctly.
        # See https://texdoc.org/serve/latexmk/0
        '-pdflatex=pdflatex -interaction=nonstopmode -halt-on-error %O %P',
        f'-aux-directory={builddir.absolute()}',
    ]

    eoptions = []
    pipe = True

    if config.args.watch:
        latexmk_command.append('-pvc')
        if config.args.open is None:
            latexmk_command.append('-view=none')
        # write pdf directly in the problem folder
        dest_path.unlink(True)
        latexmk_command.append(f'--jobname={tex_path.stem}.{language}')
        latexmk_command.append(f'-output-directory={dest_path.parent.absolute()}')
        if not config.args.error:
            latexmk_command.append('--silent')
        pipe = False
    else:
        latexmk_command.append(f'-output-directory={builddir.absolute()}')
        if config.args.open is not None:
            latexmk_command.append('-pv')
    if isinstance(config.args.open, Path):
        if shutil.which(f'{config.args.open}') == None:
            bar.warn(f"'{config.args.open}' not found. Using latexmk fallback.")
            config.args.open = True
        else:
            eoptions.append(f"$pdf_previewer = 'start {config.args.open} %O %S';")

    if getattr(config.args, '1'):
        eoptions.append('$max_repeat=1;')

    if eoptions:
        latexmk_command.extend(['-e', ''.join(eoptions)])

    latexmk_command.append(tex_path.absolute())

    def run_latexmk(stdout, stderr):
        logfile.unlink(True)
        return util.exec_command(
            latexmk_command,
            crop=False,
            preexec_fn=False,  # firefox and chrome crash with preexec_fn...
            cwd=builddir,
            stdout=stdout,
            stderr=stderr,
            env=env,
            timeout=None,
        )

    if pipe:
        # use files instead of subprocess.PIPE since later might hang
        outfile = (builddir / tex_path.name).with_suffix('.stdout')
        errfile = (builddir / tex_path.name).with_suffix('.stderr')
        with outfile.open('w') as stdout, errfile.open('w') as stderr:
            ret = run_latexmk(stdout, stderr)
        ret.err = errfile.read_text(errors='replace')  # not used
        ret.out = outfile.read_text(errors='replace')

        last = ret.out
        if not config.args.error:
            last = tail(ret.out, 25)
        if last != ret.out:
            last = f'{last}{Fore.YELLOW}Use -e to show more or see:{Style.RESET_ALL}\n{outfile}'
        ret.out = last
    else:
        ret = run_latexmk(None, None)

    if not ret.status:
        bar.error(f'Failure compiling PDF:')
        if ret.out is not None:
            print(ret.out, file=sys.stderr)
            if logfile.exists():
                print(logfile, file=sys.stderr)
        bar.error(f'return code {ret.returncode}')
        bar.error(f'duration {ret.duration}\n')
        return False

    assert not config.args.watch
    ensure_symlink(dest_path, built_pdf, True)

    bar.log(f'PDF written to {dest_path}\n')
    return True


# 1. Copy the latex/problem.tex file to tmpdir/<problem>/latex/<language>/problem.tex,
#    substituting variables.
# 2. Create tmpdir/<problem>/latex/<language>/samples.tex.
# 3. Run latexmk and link the resulting problem.<language>.pdf into the problem directory.
def build_problem_pdf(problem, language, solution=False, web=False):
    """
    Arguments:
    -- language: str, the two-letter language code appearing the file name, such as problem.en.tex
    """
    main_file = 'solution' if solution else 'problem'
    main_file += '-web.tex' if web else '.tex'

    bar = PrintBar(f'{main_file[:-3]}{language}.pdf')
    bar.log(f'Building PDF for language {language}')

    prepare_problem(problem, language)

    builddir = latex_builddir(problem, language)

    local_data = Path(main_file)
    util.copy_and_substitute(
        local_data if local_data.is_file() else config.tools_root / 'latex' / main_file,
        builddir / main_file,
        {
            'problemlabel': problem.label,
            'problemyamlname': problem.settings.name[language].replace('_', ' '),
            'problemauthor': problem.settings.author,
            'timelimit': get_tl(problem),
            'problemdir': problem.path.absolute().as_posix(),
            'problemdirname': problem.name,
            'builddir': builddir.as_posix(),
        },
    )

    return build_latex_pdf(builddir, builddir / main_file, language, bar, problem.path)


def build_problem_pdfs(problem, solutions=False, web=False):
    """Build PDFs for various languages. If list of languages is specified,
    (either via config files or --language arguments), build those. Otherwise
    build all languages for which there is a statement latex source.
    """
    if config.args.languages is not None:
        for lang in config.args.languages:
            if lang not in problem.statement_languages:
                message(
                    f'No statement source for language {lang}',
                    problem.name,
                    color_type=MessageType.FATAL,
                )
        languages = config.args.languages
    else:
        languages = problem.statement_languages
        # For solutions, filter for `solution.xy.tex` files that exist.
        if solutions:
            filtered_languages = []
            for lang in languages:
                if (problem.path / 'problem_statement' / f'solution.{lang}.tex').exists():
                    filtered_languages.append(lang)
                else:
                    message(
                        f'solution.{lang}.tex not found', problem.name, color_type=MessageType.WARN
                    )
            languages = filtered_languages
    if config.args.watch and len(languages) > 1:
        fatal('--watch does not work with multiple languages. Please use --language')
    return all([build_problem_pdf(problem, lang, solutions, web) for lang in languages])


def find_logo():
    for directory in ['', '../']:
        for extension in ['pdf', 'png', 'jpg']:
            logo = Path(directory + 'logo.' + extension)
            if logo.exists():
                return logo
    return config.tools_root / 'latex' / 'images' / 'logo-not-found.pdf'


def build_contest_pdf(contest, problems, tmpdir, language, solutions=False, web=False):
    builddir = tmpdir / contest / 'latex'
    builddir.mkdir(parents=True, exist_ok=True)
    build_type = 'solution' if solutions else 'problem'

    main_file = 'solutions' if solutions else 'contest'
    main_file += '-web.tex' if web else '.tex'

    bar = PrintBar(f'{main_file[:-3]}{language}.pdf')
    bar.log(f'Building PDF for language {language}')

    default_config_data = {
        'title': 'TITLE',
        'subtitle': '',
        'year': 'YEAR',
        'author': 'AUTHOR',
        'testsession': '',
    }
    config_data = contest_yaml()
    for x in default_config_data:
        if x not in config_data:
            config_data[x] = default_config_data[x]
    config_data['testsession'] = '\\testsession' if config_data.get('testsession') else ''
    config_data['logofile'] = find_logo().as_posix()

    local_contest_data = Path('contest_data.tex')
    util.copy_and_substitute(
        (
            local_contest_data
            if local_contest_data.is_file()
            else config.tools_root / 'latex' / 'contest_data.tex'
        ),
        builddir / 'contest_data.tex',
        config_data,
    )

    problems_data = ''

    if solutions:
        # include a header slide in the solutions PDF
        headerlangtex = Path(f'solution_header.{language}.tex')
        headertex = Path('solution_header.tex')
        if headerlangtex.exists():
            problems_data += f'\\input{{{headerlangtex}}}\n'
        elif headertex.exists():
            problems_data += f'\\input{{{headertex}}}\n'

    local_per_problem_data = Path(f'contest-{build_type}.tex')
    per_problem_data = (
        local_per_problem_data
        if local_per_problem_data.is_file()
        else config.tools_root / 'latex' / f'contest-{build_type}.tex'
    ).read_text()

    for problem in problems:
        if build_type == 'problem':
            prepare_problem(problem, language)

        if solutions:
            solutiontex = problem.path / 'problem_statement' / 'solution.tex'
            solutionlangtex = problem.path / 'problem_statement' / f'solution.{language}.tex'
            if solutionlangtex.is_file():
                # All is good
                pass
            elif solutiontex.is_file():
                bar.warn(f'Rename solution.tex to solution.{language}.tex', problem.name)
                continue
            else:
                bar.warn(f'solution.{language}.tex not found', problem.name)
                continue

        problems_data += util.substitute(
            per_problem_data,
            {
                'problemlabel': problem.label,
                'problemyamlname': problem.settings.name[language].replace('_', ' '),
                'problemauthor': problem.settings.author,
                'timelimit': get_tl(problem),
                'problemdir': problem.path.absolute().as_posix(),
                'problemdirname': problem.name,
                'builddir': latex_builddir(problem, language).as_posix(),
            },
        )

    if solutions:
        # include a footer slide in the solutions PDF
        footerlangtex = Path(f'solution_footer.{language}.tex')
        footertex = Path('solution_footer.tex')
        if footerlangtex.exists():
            problems_data += f'\\input{{{footerlangtex}}}\n'
        elif footertex.exists():
            problems_data += f'\\input{{{footertex}}}\n'

    (builddir / f'contest-{build_type}s.tex').write_text(problems_data)

    return build_latex_pdf(builddir, Path(main_file), language, bar)


def build_contest_pdfs(contest, problems, tmpdir, lang=None, solutions=False, web=False):
    if lang:
        return build_contest_pdf(contest, problems, tmpdir, lang, solutions, web)

    """Build contest PDFs for all available languages"""
    statement_languages = set.intersection(*(set(p.statement_languages) for p in problems))
    if not statement_languages:
        message(
            'No statement language present in every problem.', contest, color_type=MessageType.FATAL
        )
    if config.args.languages is not None:
        languages = config.args.languages
        for lang in set(languages) - statement_languages:
            message(
                f'Unable to build all statements for language {lang}',
                contest,
                color_type=MessageType.FATAL,
            )
    else:
        languages = statement_languages
    if config.args.watch and len(languages) > 1:
        message(
            '--watch does not work with multiple languages. Please use --language',
            contest,
            color_type=MessageType.FATAL,
        )
    return all(
        [build_contest_pdf(contest, problems, tmpdir, lang, solutions, web) for lang in languages]
    )


def get_argument_for_command(texfile, command):
    """Return the (whitespace-normalised) argument for the given command in the given texfile.
    If texfile contains `\foo{bar  baz }`, returns the string 'bar baz'.
    The command is given without backslash.


    Assumptions:
    the command and its argument are on the same line,
    and that the argument contains no closing curly brackets.
    """

    for line in texfile:
        regex = r'\\' + command + r'\{(.*)\}'
        match = re.search(regex, line)
        if match:
            return ' '.join(match.group(1).split())
    return None
