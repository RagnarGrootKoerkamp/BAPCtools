%-------------------------------------------------------------------------------
% This is the file bapc2017.cls.
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
% Authors: Josse van Dobben de Bruyn, Joris van Rantwijk
%-------------------------------------------------------------------------------
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{bapc2017}[2016/09/20, BAPC2016 class v0.7]

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
\nonzeroparskip

% Require some packages.
\RequirePackage{eqparbox}
\RequirePackage{tabularx}
\RequirePackage{environ}

% Add a relatively unknown package for hyperlinks,
% since hyperref messes up the entire document.
\RequirePackage{navigator}
\newcommand{\href}[2]{\urllink{#1}{#2}}

\newcommand{\todo}[1]{{\color{red}[#1]}}

%-------------------------------------------------------------------------------
% ThisIsNotABlankPage: clears to an odd page. If a blank page is created, then
% it is decorated with the text "This is not a blank page".
%-------------------------------------------------------------------------------
\newcommand{\ThisIsNotABlankPage}{
	\cleartooddpage[
		\thispagestyle{empty}
		\vfill
		\begin{center}
			\sffamily\huge This is not a blank page.
		\end{center}
		\vspace*{10.55cm} % slightly above vertical centre.
		\vfill
	]
}

%-------------------------------------------------------------------------------
% Sectioning commands and list of problems.
% 
% Creating a new list for the problems (instead of using the tableofcontents)
% turned out to be a lot easier in terms of custom formatting.
%-------------------------------------------------------------------------------
\renewcommand{\thesection}{\Alph{section}}
\newlistof{listofproblems}{lop}{Problems}
\newcounter{SampleCount}
\renewcommand{\printloptitle}[1]{
	\outline{1}{#1}
	\Large
	\eqmakebox[letter][c]{}
	\quad
	\eqmakebox[titel][l]{\huge\textbf{#1}}
	\par
	\vspace*{-1cm}
}
\renewcommand{\afterloptitle}{\thispagestyle{empty}\afterchaptertitle}
\newcommand{\problemname}[1]{
	\ThisIsNotABlankPage
	\outline{1}{#1}
	\section{#1}
	\rmfamily

	% Formatting the list of problems on the title page:
	\cftaddtitleline{lop}{sec}{
		\vspace{.4pt}
		\Large
		\eqmakebox[letter][c]{\thesection}
		\quad
		\eqmakebox[titel][l]{#1}
		\par
	}{}
	\setcounter{SampleCount}{0}
}

%-------------------------------------------------------------------------------
% Setting headings.
%-------------------------------------------------------------------------------
\copypagestyle{bapc}{headings}
\makepsmarks{bapc}{
	\createmark{section}{both}{shownumber}{Problem }{: }
}
\pagestyle{bapc}
\nouppercaseheads


%-------------------------------------------------------------------------------
% Environments for specifying Input, Output and optionally Explanation.
%-------------------------------------------------------------------------------
\newenvironment{Input}{
	\subsection*{Input}
}{}
\newenvironment{Output}{
	\subsection*{Output}
}{}
\newenvironment{Explanation}{
	\subsection*{Explanation of samples}
}{}

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
	\multicolumn{1}{l}{\large \bfseries\textrm{Sample #1 \arabic{SampleCount}}}
}
\NewEnviron{Sample}{
	\par\bigskip\noindent%
	\normalsize%
	\ttfamily%
	\frenchspacing% to prevent extra spaces after punctuation. https://tex.stackexchange.com/q/118455/43242
	\stepcounter{SampleCount}%
	\renewcommand\baselinestretch{1}\selectfont% <-- combining various lengths in order
	\setlength{\extrarowheight}{2.5pt}%              to set the top and bottom padding; see
	\begin{tabularx}{\textwidth}{|X|X|}%             http://tex.stackexchange.com/a/31704
		\mySampleHeading{Input} & \mySampleHeading{Output} \\
		\hline
		\BODY[2pt]
		\hline
	\end{tabularx}%
	\rmfamily
}

%-------------------------------------------------------------------------------
% The following are required for the overall layout:
%-------------------------------------------------------------------------------
\usepackage[english]{babel}
\usepackage{lmodern}
\usepackage{graphicx}
\usepackage{courier}
%-------------------------------------------------------------------------------
% The following are required for most problems:
%-------------------------------------------------------------------------------
\usepackage{amsmath,amssymb}
\usepackage{wrapfig}
\usepackage{tikz}
\usepackage{enumitem}	% [noitemsep] for smaller lists

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
\renewcommand\@memfront@floats{}
\renewcommand\@memmain@floats{}
\renewcommand\@memback@floats{}
\makeatletter


%-------------------------------------------------------------------------------
% Reduce font size of figure captions.
%-------------------------------------------------------------------------------
\captionnamefont{\small}
\captiontitlefont{\small}

\endinput
