%-------------------------------------------------------------------------------
% This is the file bapc.cls.
%
% It is a copy of the file bapc2016.cls, with only the file name changed and
% this line added.
%
% It provides a workable environment for typesetting ICPC-style programming
% contests. The Benelux Algorithm Programming Contest (BAPC) is a local
% preliminary contest, even before the regionals for Northwestern Europe.
%
% The entire class is based on the memoir class. Every option is immediately
% passed to memoir. The BAPC class doesn't provide any additional options.
%
% Authors: Josse van Dobben de Bruyn, Joris van Rantwijk, Ragnar Groot Koerkamp
%-------------------------------------------------------------------------------
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{bapc}

%\RequirePackage{frcursive}

%-------------------------------------------------------------------------------
% ThisIsNotABlankPage: clears to an odd page. If a blank page is created, then
% it is decorated with the text "This is not a blank page".
%-------------------------------------------------------------------------------

\newcommand{\ThisIsNotABlankPage}{
	\cleartooddpage[
		\thispagestyle{empty}
		\vfill
		\begin{center}
			\huge{%
				\langblank{}%
			}
			%\includegraphics{images/blank-page-fr.png}
		\end{center}
		\vspace*{5.55cm} % slightly above vertical centre.
		\vfill
	]
}
\DeclareOption{web}{
	\renewcommand{\ThisIsNotABlankPage}{\clearpage}
}

% Passes any class options to the underlying memoir class.
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{memoir}}
\ProcessOptions

% Load LaTeX's memoir class.
% (Joris: increase font size)
\LoadClass[a4paper,11pt,svgnames]{memoir}

% (Joris: increase line spacing)
\linespread{1.1}

% (Joris: add space between paragraphs)
\setlength{\parindent}{0pt}
\setlength{\medskipamount}{0pt} % Prevent spaces before/after lstlisting.
\nonzeroparskip

% Require some packages.
\RequirePackage{bapcbase}
\RequirePackage{microtype}
\RequirePackage{eqparbox}
\RequirePackage{tabularx}
\RequirePackage{environ}
\RequirePackage{etoolbox}
\RequirePackage{float}
\RequirePackage{upquote}
\RequirePackage{tocloft}
\RequirePackage{xparse}
\RequirePackage{siunitx}
\sisetup{per-mode=symbol}

\RequirePackage[hidelinks,bookmarks=true,pdfusetitle]{hyperref}

\newcommand{\todo}[1]{{\color{red}[#1]}}

%-------------------------------------------------------------------------------
% Sectioning commands and list of problems.
%
% Creating a new list for the problems (instead of using the tableofcontents)
% turned out to be a lot easier in terms of custom formatting.
%-------------------------------------------------------------------------------
\renewcommand{\thesection}{\problemlabel}
\newcommand{\listofproblemsname}{\langproblems{}}
\newlistof{listofproblems}{lop}{\listofproblemsname}
\newlistentry{problem}{lop}{0}
\newcounter{SampleCount}
\renewcommand{\printloptitle}[1]{
	\hfill
	\sffamily
	\Large
	\eqmakebox[letter][c]{}
	\quad
	\eqmakebox[titel][l]{\huge\textbf{#1}}
	\hfill
	\vspace*{-1cm}
}
\renewcommand{\afterloptitle}{\thispagestyle{empty}\afterchaptertitle}
\setlength{\cftparskip}{0.45em}
\cftpagenumbersoff{section}
\renewcommand{\cftsectionleader}{}

\newcommand{\ProblemHeading}[1]{
	\ThisIsNotABlankPage
	\section{#1}
	\vspace{-2.3em}
	\hfill
	\ifdefempty{\timelimit}{}{{\color{darkgray}\fontfamily{qcr}\langtimelimit{}: \timelimit{}s}}

	\setcounter{SampleCount}{0}
	\setcounter{figure}{0}

	\rmfamily

	% Formatting the list of problems on the title page:
	\cftaddtitleline{lop}{section}{
		\vspace{.4pt}
		\hfill
		\sffamily
		\Large
		\eqmakebox[letter][c]{\thesection}
		\quad
		\eqmakebox[titel][l]{#1}%
		\hfill
	}{}
}

%-------------------------------------------------------------------------------
% Setting headings.
%-------------------------------------------------------------------------------
\copypagestyle{bapc}{headings}
\makepsmarks{bapc}{
	\createmark{section}{both}{shownumber}{\langproblem{} }{: }
}
\pagestyle{bapc}
\nouppercaseheads


%-------------------------------------------------------------------------------
% Environment for specifying Samples.
%
% In 2016 the BAPC jury will provide only one test case per file, instead of
% multiple test cases (as is customary at the BAPC). This calls for a different
% layout, and therefore a complete rewrite of parts of the LaTeX code. The
% following code was written specifically for BAPC 2016.
%
% We want to create an environment based upon the tabularx environment.
% Unfortunately, this is not so easy, as the code for the tabularx environment
% contains some strange hacks that are documented reasonably well.
%
% For more information, please refer to http://tex.stackexchange.com/a/42331 .
% It is worth mentioning that this is only part of the story. The documentation
% of the tabularx package reveals that this workaround only works if
% \endtabularx is the first token of the `end code' of the environment.
% However, we want to have a \hline before that, so this code is no good.
%
% A solution to this problem was found on http://tex.stackexchange.com/a/111488 .
%-------------------------------------------------------------------------------
\newcommand{\mySampleHeading}[1]{
	\multicolumn{1}{l}{\large \bfseries\textrm{#1 \arabic{SampleCount}}}
}
\newcommand{\SampleListing}[1]{
	\lstinputlisting[aboveskip=-0.7\baselineskip,belowskip=-0.9\baselineskip,inputencoding=utf8/latin1,basicstyle=\ttfamily]{#1}
}
\newcommand{\InteractiveSampleListing}[1]{
	\lstinputlisting[aboveskip=-1.0\baselineskip,belowskip=-1\baselineskip,inputencoding=utf8/latin1,basicstyle=\ttfamily]{#1}
}
\newcommand{\SideBySideSample}[2]{
	\par\bigskip\noindent%
	\normalsize%
	\stepcounter{SampleCount}%
	\renewcommand\baselinestretch{1}\selectfont% <-- combining various lengths in order
	\setlength{\extrarowheight}{2.5pt}%              to set the top and bottom padding; see
	\begin{tabularx}{\textwidth}{|X|X|}%             http://tex.stackexchange.com/a/31704
		\mySampleHeading{\langinputsample{}} & \mySampleHeading{\langoutputsample{}} \\
		\hline
		\SampleListing{#1}~ &
		\SampleListing{#2}~ \\
		\hline
	\end{tabularx}%
	\rmfamily
}

\newcommand{\FullWidthSample}[2]{
	\par\bigskip\noindent%
	\normalsize%
	\stepcounter{SampleCount}%
	\renewcommand\baselinestretch{1}\selectfont% <-- combining various lengths in order
	\setlength{\extrarowheight}{2.5pt}%              to set the top and bottom padding; see
	\begin{tabularx}{\textwidth}{|X|}%             http://tex.stackexchange.com/a/31704
		\mySampleHeading{\langinput{}} \\
		\hline
		\SampleListing{#1}~ \\
		\hline
	\end{tabularx}%
	\nopagebreak
	\par
	\noindent
	\begin{tabularx}{\textwidth}{|X|}%
		\mySampleHeading{\langoutput{}} \\
		\hline
		\SampleListing{#2}~ \\
		\hline
	\end{tabularx}%
	\rmfamily
}

\newcommand{\SideBySideSampleNoHeading}[2]{
	\normalsize%
	\renewcommand\baselinestretch{1}\selectfont% <-- combining various lengths in order
	\setlength{\extrarowheight}{2.5pt}%              to set the top and bottom padding; see
	\begin{tabularx}{\textwidth}{|X|X|}%             http://tex.stackexchange.com/a/31704
		\hline
		\SampleListing{#1}~ &
		\SampleListing{#2}~ \\
		\hline
	\end{tabularx}%
	\rmfamily
}

\newcommand{\FullWidthSampleNoHeading}[2]{
	\normalsize%
	\renewcommand\baselinestretch{1}\selectfont% <-- combining various lengths in order
	\setlength{\extrarowheight}{2.5pt}%              to set the top and bottom padding; see
	\begin{tabularx}{\textwidth}{|X|}%               http://tex.stackexchange.com/a/31704
		\hline
		\SampleListing{#1}~ \\
		\hline
	\end{tabularx}%
	\nopagebreak
	\par
	\noindent
	\begin{tabularx}{\textwidth}{|X|}%
		\hline
		\SampleListing{#2}~ \\
		\hline
	\end{tabularx}%
	\rmfamily
}

\newlength{\PS@idealwidth}
\newsavebox{\PS@inputbox}
\newsavebox{\PS@outputbox}
\newlength{\PS@inputwidth}
\newlength{\PS@outputwidth}

\newcommand{\Sample}[2]{
	\savebox{\PS@inputbox}{\SampleListing{#1}}
	\savebox{\PS@outputbox}{\SampleListing{#2}}
	\setlength{\PS@idealwidth}{\dimeval{0.5\textwidth - 2\arraycolsep}}
	\settowidth{\PS@inputwidth}{\usebox{\PS@inputbox}}
	\settowidth{\PS@outputwidth}{\usebox{\PS@outputbox}}
	% Check if too wide for side-by-side
	\ifdim\PS@inputwidth<\PS@idealwidth
		\ifdim\PS@outputwidth<\PS@idealwidth
			% If both input and output are small enough, print side-by-side.
			\SideBySideSample{#1}{#2}
		\else
			% If output width is too large, print full-width.
			\FullWidthSample{#1}{#2}
		\fi
	\else
		% If input width is too large, print full-width.
		\FullWidthSample{#1}{#2}
	\fi
}

\newcommand{\SampleNoHeading}[2]{
	\savebox{\PS@inputbox}{\SampleListing{#1}}
	\savebox{\PS@outputbox}{\SampleListing{#2}}
	\setlength{\PS@idealwidth}{\dimeval{0.5\textwidth - 2\arraycolsep}}
	\settowidth{\PS@inputwidth}{\usebox{\PS@inputbox}}
	\settowidth{\PS@outputwidth}{\usebox{\PS@outputbox}}
	% Check if too wide for side-by-side
	\ifdim\PS@inputwidth<\PS@idealwidth
		\ifdim\PS@outputwidth<\PS@idealwidth
			% If both input and output are small enough, print side-by-side.
			\SideBySideSampleNoHeading{#1}{#2}
		\else
			% If output width is too large, print full-width.
			\FullWidthSampleNoHeading{#1}{#2}
		\fi
	\else
		% If input width is too large, print full-width.
		\FullWidthSampleNoHeading{#1}{#2}
	\fi
}

\newcommand{\MultipassSampleHeading}{
	\stepcounter{SampleCount}
	\par%
	\begin{tabularx}{0.983\textwidth}{X}%
		\centering \large\bfseries\textrm{\langsamplecase{} \arabic{SampleCount}}%
	\end{tabularx}
  \par%
	\nopagebreak[4]%
}

\newcommand{\SamplePass}[3]{%
  \begin{samepage}%
	\begin{tabularx}{0.983\textwidth}{XXX}%
		\large\bfseries\textrm{\langinput{}} \hfill%
		& %
		\centering \large\bfseries\textrm{\langpass{} #1}%
		& %
		\hfill \large\bfseries\textrm{\langoutput{}}\\%
	\end{tabularx}
  \\%
  \SampleNoHeading{#2}{#3}%
  \end{samepage}%
}


\newcommand{\InteractiveSampleHeading}{
	\par\bigskip\noindent%
	\normalsize%
	\stepcounter{SampleCount}%
	\begin{tabularx}{0.983\textwidth}{XXX}%
		\large\bfseries\textrm{\langread{}} \hfill%
		& %
		\centering \large\bfseries\textrm{\langsampleinteraction{} \arabic{SampleCount}}%
		& %
		\hfill \large\bfseries\textrm{\langwrite{}}\\%
	\end{tabularx}
	\nopagebreak
	\vspace{-1.0em}
	\par
}
\newcommand{\InteractiveWrite}[1]{
	\noindent
	\normalsize
	\ttfamily
	\frenchspacing% to prevent extra spaces after punctuation. https://tex.stackexchange.com/q/118455/43242
	\hfill\framebox[0.55\textwidth][l]{%
		\parbox[t]{\dimexpr0.55\textwidth-2\fboxsep-2\fboxrule\relax}{
			\vspace{-.4em}%
			\strut%
			\InteractiveSampleListing{#1}
			\vspace{-.4em}%
			\strut%
		}
	}
	\nopagebreak
	\vspace{-0.4em}
	\par
}
\newcommand{\InteractiveRead}[1]{
	\noindent
	\normalsize
	\ttfamily
	\frenchspacing% to prevent extra spaces after punctuation. https://tex.stackexchange.com/q/118455/43242
	\framebox[0.55\textwidth][l]{%
		\parbox[t]{\dimexpr0.55\textwidth-2\fboxsep-2\fboxrule\relax}{
			\vspace{-.4em}%
			\strut%
			\InteractiveSampleListing{#1}
			\vspace{-.4em}%
			\strut%
		}
	}
	\nopagebreak
	\vspace{-0.4em}
	\par%
}

\newcommand{\InteractivePass}[1]{
	\par\bgroup\bigskip\noindent%
	\centering\large\bfseries\textrm{\langpass{} #1}
	\nopagebreak
	\vspace{-1.0em}
	\par\egroup
}

%-------------------------------------------------------------------------------
% The following are required for the overall layout:
%-------------------------------------------------------------------------------
\let\sffamilyFB\sffamily% Prevent error if babel fr loads \sffamilyFB in cache
\let\ttfamilyFB\ttfamily
\let\rmfamilyFB\rmfamily
\usepackage[none]{hyphenat} % Disable hyphenation with language [none]
\usepackage{lmodern}
\usepackage{courier}
\usepackage[T1]{fontenc} % Standard
\usepackage[utf8]{inputenc} % UTF-8 support
% https://tex.stackexchange.com/questions/270557/undefined-control-sequence-on-onehalfspacing
\DisemulatePackage{setspace}
\usepackage{setspace}

%-------------------------------------------------------------------------------
% The following are required for most problems:
%-------------------------------------------------------------------------------
\usepackage{amsmath,amssymb}
\usepackage{tikz}
\usepackage{tikz-qtree}
\usetikzlibrary{arrows}
\usetikzlibrary{shapes}
\usetikzlibrary{backgrounds}
\usetikzlibrary{patterns}
\usetikzlibrary{positioning}
\usetikzlibrary{scopes}
\usetikzlibrary{shapes.geometric}
\usepackage{enumitem}	% [noitemsep] for smaller lists
\usepackage{textcomp} % textquotesingle: '
\usepackage{pgfplots}
\pgfplotsset{compat=1.17}


%-------------------------------------------------------------------------------
% Set margins (using commands from memoir.cls).
%-------------------------------------------------------------------------------
\setlrmarginsandblock{27mm}{27mm}{*} % left and right margins
\setulmarginsandblock{*}{40mm}{0.8}  % upper and lower margins
\checkandfixthelayout


%-------------------------------------------------------------------------------
% Change figure numbering.
%
% Taken from http://tex.stackexchange.com/a/116820 .
%-------------------------------------------------------------------------------
\makeatletter
\counterwithout{figure}{chapter}
\counterwithout{table}{chapter}
\@addtoreset{figure}{section} % Added from https://tex.stackexchange.com/a/45931:
\@addtoreset{table}{section}  % Makes sure that hyperlinks go to correct problem
\renewcommand\@memfront@floats{}
\renewcommand\@memmain@floats{}
\renewcommand\@memback@floats{}
\makeatletter

\renewcommand{\illustration}[3]{
	\begin{wrapfigure}{r}{#1\textwidth}
	\vspace{-10pt}
	\includegraphics[width=#1\textwidth]{#2}
	\ifstrempty{#3}{
		\vspace{-25pt}
	}{
		\begin{flushright}
		\vspace{-9pt}
		\tiny #3
		\end{flushright}
		\vspace{-15pt}
	}
	\end{wrapfigure}
	%\par
	%\noindent
}

%% Number figures as A.1 A.2... B.1 B.2...
\renewcommand{\thefigure}{\thesection.\arabic{figure}}

%-------------------------------------------------------------------------------
% Reduce font size of figure captions.
%-------------------------------------------------------------------------------
\captionnamefont{\small}
\captiontitlefont{\small}

\endinput
