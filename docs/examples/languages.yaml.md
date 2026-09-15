# `languages.yaml`

This is the languages.yaml shipped with BAPCtools.
It is mostly identical to the version that problemtools ships, see [here](https://github.com/Kattis/problemtools/blob/6010cbaa37a1612117f49566b2fff8646d53faa2/problemtools/config/languages.yaml).

```yaml
# Language configuration for Kattis Problem Format
# Copyright (c) 2010-2026 Kattis and all respective contributors
# ================================================
c:
    name: 'C'
    priority: 950
    files: '*.c'
    compile: 'gcc -g -O2 -std=gnu11 -o {binary} {files} -lm -Wall -Wfatal-errors -fdiagnostics-color=always'
    run: '{binary}'

cpp:
    name: 'C++'
    priority: 1000
    files: '*.cc *.C *.cpp *.cxx *.c++'
    compile: 'g++ -g -O2 -std=gnu++23 -o {binary} {files} -Wall -Wfatal-errors -fdiagnostics-color=always'
    run: '{binary}'

csharp:
    name: 'C#'
    priority: 700
    files: '*.cs'
    compile: 'mcs -out:{binary}.exe -optimize+ -r:System.Numerics {files}'
    run: 'mono {binary}.exe'

cobol:
    name: 'Cobol'
    priority: 50
    files: '*.cob'
    compile: 'cobc -o {binary} -g -O2 -std=default -free -x -static {files}'
    run: '{binary}'

fsharp:
    name: 'F#'
    priority: 675
    files: '*.fs'
    compile: 'fsharpc --out:{binary}.exe --optimize+ -r:System.Numerics {files}'
    run: 'mono {binary}.exe'

go:
    name: 'Go'
    priority: 400
    files: '*.go'
    compile: 'gccgo -g -o {binary} -static-libgcc {files}'
    run: '{binary}'

haskell:
    name: 'Haskell'
    priority: 600
    files: '*.hs *.c'
    compile: 'ghc -O2 -ferror-spans -threaded -rtsopts -tmpdir {path} -o {binary} {files}'
    run: '{binary} +RTS -M{memlim}m -K8m -RTS'

java:
    name: 'Java'
    priority: 851
    files: '*.java'
    compile: 'javac -encoding UTF-8 -cp {path} -sourcepath {path} -d {path} {files}'
    run: 'java -Dfile.encoding=UTF-8 -XX:+UseSerialGC -Xss64m -Xms{memlim}m -Xmx{memlim}m -cp {path} {mainclass}'

javascript:
    name: 'JavaScript'
    priority: 500
    files: '*.js'
    compile: 'js24 -c {files}'
    run: 'js24 "{mainfile}"'

kotlin:
    name: 'Kotlin'
    priority: 250
    files: '*.kt'
    compile: 'kotlinc -d {path}/ -- {files}'
    run: 'kotlin -Dfile.encoding=UTF-8 -J-XX:+UseSerialGC -J-Xss64m -J-Xms{memlim}m -J-Xmx{memlim}m -cp {path}/ {Mainclass}Kt'

lisp:
    name: 'Common Lisp'
    priority: 200
    files: '*.lisp *.cl'
    compile: 'sbcl --noinform --noprint --non-interactive --eval ''(if (equal (compile-file "{mainfile}") NIL) (sb-ext:exit :code 43) ())'' '
    run: 'sbcl --noinform --non-interactive --load "{mainfile}"'

ocaml:
    name: 'OCaml'
    priority: 375
    files: '*.ml'
    compile: 'ocamlopt -o {binary} unix.cmxa str.cmxa bigarray.cmxa {files}'
    run: '{binary}'

objectivec:
    name: 'Objective C'
    priority: 300
    files: '*.m *.c'
    # The postargs for the compile command are '-lm -lobjc `gnustep-config --objc-flags` -lgnustep-base -o {binary}', edited to remove -I. and -I(home dir of user running the command), and to remove duplicate definition of GNUSTEP_BASE_LIBRARY
    compile: 'gcc -O2 -std=gnu99 {files} -lm -lobjc -MMD -MP -DGNUSTEP -DGNUSTEP_BASE_LIBRARY=2 -DGNU_GUI_LIBRARY=1 -DGNU_RUNTIME=1 -fno-strict-aliasing -fexceptions -fobjc-exceptions -D_NATIVE_OBJC_EXCEPTIONS -fPIC -Wall -DGSWARN -DGSDIAGNOSE -Wno-import -g -O2 -fstack-protector --param=ssp-buffer-size=4 -D_FORTIFY_SOURCE=2 -Wformat -Wformat-security -Werror=format-security -fgnu-runtime -fconstant-string-class=NSConstantString -I/usr/local/include/GNUstep -I/usr/include/GNUstep -lgnustep-base -o {binary}'
    run: '{binary}'

pascal:
    name: 'Pascal'
    priority: 350
    files: '*.pas'
    compile: 'fpc -o"{mainfile}.out" -O2 -XS -Xt "{mainfile}"'
    run: '"{mainfile}.out"'

php:
    name: 'PHP'
    priority: 450
    files: '*.php'
    compile: 'php -n -d display_errors=stderr -d html_errors=0 -l {files}'
    run: 'php -n -d display_errors=stderr -d html_errors=0 -d memory_limit={memlim}m -f "{mainfile}"'

prolog:
    name: 'Prolog'
    priority: 100
    files: '*.pl'
    compile: 'swipl -O -q -g main -t halt -o {binary} -c {files}'
    run: '{binary}'

# *.py2 files are unconditionally Python 2. *.py files are only counted
# as Python 2 (over Python 3) when they carry a python2 shebang; a *.py
# file without one is only evidence for python3. Priority is higher than
# python3's so that ties (i.e. every *.py file in the program has the
# shebang) resolve to python2.
python2:
    name: 'Python 2 (w/PyPy)'
    priority: 860
    files: '*.py *.py2'
    shebang_files: '*.py'
    shebang: '^#!.*python2\b'
    compile: 'pypy2 -m py_compile {files}'
    run: 'pypy2 "{mainfile}"'

python3:
    name: 'Python 3 (w/PyPy3)'
    priority: 850
    files: '*.py *.py3'
    compile: 'pypy3 -m py_compile {files}'
    run: 'pypy3 "{mainfile}"'

ruby:
    name: 'Ruby'
    priority: 650
    files: '*.rb'
    # Note that this compile command only syntax-checks the main file --
    # unfortunately the ruby -c command does not provide the option to
    # syntax-check multiple files.
    compile: 'ruby -c "{mainfile}"'
    run: 'ruby "{mainfile}"'

rust:
    name: 'Rust'
    priority: 575
    files: '*.rs'
    compile: 'rustc -o{binary} -O --crate-type bin --edition=2018 {files}'
    run: '{binary}'

scala:
    name: 'Scala'
    priority: 550
    files: '*.sc *.scala'
    compile: 'scalac -encoding UTF-8 -sourcepath {path} -d {path} {files}'
    run: 'scala -J-Xmx{memlim}m -classpath {path} {mainclass}'

# the following languages are BAPCtools extensions
# ================================================

cpython2:
    name: 'Python 2 (w/PyPy)'
    priority: 859
    files: '*.py *.py2'
    shebang_files: '*.py'
    shebang: '^#!.*python2\b'
    compile: 'python2 -m py_compile {files}'
    run: 'python2 "{mainfile}"'

cpython3:
    name: 'Python 3'
    priority: 849
    files: '*.py *.py3 *.cpy'
    compile: 'python3 -m py_compile {files}'
    run: 'python3 "{mainfile}"'

# Executes any .sh file.
shell:
    name: 'Shell'
    priority: 910
    files: '*.sh'
    run: 'sh "{mainfile}"'

# Executes any .bash file.
bash:
    name: 'Bash'
    priority: 920
    files: '*.bash'
    run: 'bash "{mainfile}"'

```
