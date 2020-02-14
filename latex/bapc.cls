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
			\huge{This page is intentionally left blank.}
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
\RequirePackage{eqparbox}
\RequirePackage{tabularx}
\RequirePackage{environ}
\RequirePackage{etoolbox}
\RequirePackage{float}
\RequirePackage{listingsutf8}

% Add a relatively unknown package for hyperlinks,
% since hyperref messes up the entire document.
\RequirePackage{navigator}
\newcommand{\href}[2]{\urllink{#1}{#2}}

\newcommand{\todo}[1]{{\color{red}[#1]}}

%-------------------------------------------------------------------------------
% Sectioning commands and list of problems.
% 
% Creating a new list for the problems (instead of using the tableofcontents)
% turned out to be a lot easier in terms of custom formatting.
%-------------------------------------------------------------------------------
\renewcommand{\thesection}{\problemlabel}
\newlistof{listofproblems}{lop}{Problems}
\newcounter{SampleCount}
\renewcommand{\printloptitle}[1]{
	\outline{1}[problems]{#1}
	\protect\jumplink{problems}{
	\Large
	\eqmakebox[letter][c]{}
	\quad
	\eqmakebox[titel][l]{\huge\textbf{#1}}
	}
	\par
	\vspace*{-1cm}
}
\renewcommand{\afterloptitle}{\thispagestyle{empty}\afterchaptertitle}

\newcommand{\timelimit}{TIMELIMIT MISSING}
\newcommand{\problemlabel}{} % Empty to hide activity chart
\newcommand{\problemyamlname}{Problem name}
\newcommand{\problemauthor}{Problem author}
\newcommand{\fullproblemtitle}{\problemlabel: \problemyamlname}

\newcommand{\problemname}[1]{
	\ThisIsNotABlankPage
	\ifblank{#1}{
		\section{\problemyamlname}
	}{
		\section{#1}
	}
	\vspace{-2.3em}
	\hfill
	\ifdefempty{\timelimit}{}{\color{darkgray}\fontfamily{qcr}Time limit: \timelimit{}s}
	\ifblank{#1}{
		\outline[]{1}[\thesection]{\problemyamlname}
	}{
		\outline[]{1}[\thesection]{#1}
	}

	\rmfamily

	% Formatting the list of problems on the title page:
	\cftaddtitleline{lop}{sec}{
		\vspace{.4pt}
		\protect\jumplink{\thesection}{
		\Large
		\eqmakebox[letter][c]{\thesection}
		\quad
		\ifblank{#1}{
			\eqmakebox[titel][l]{\problemyamlname}
		}{
			\eqmakebox[titel][l]{#1}
		}
		}
		\par
	}{}
	\setcounter{SampleCount}{0}
	\setcounter{figure}{0}
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
\newenvironment{Interaction}{
	\subsection*{Interaction}
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



\newcommand{\InteractiveSampleHeading}{
	\par\noindent%
	\stepcounter{SampleCount}%
	\begin{tabularx}{0.983\textwidth}{XXX}%
		\large\bfseries\textrm Read \hfill%
		& %
		\centering \large\bfseries\textrm Sample Interaction
		\arabic{SampleCount}%
		& %
		\hfill \large\bfseries\textrm Write \\%
	\end{tabularx}
	\par
}
\NewEnviron{InteractiveWrite}{
	\noindent
	\normalsize
	\ttfamily
	\frenchspacing% to prevent extra spaces after punctuation. https://tex.stackexchange.com/q/118455/43242
	\hfill\framebox[0.55\textwidth][l]{%
		\parbox[t]{\textwidth}{
			\vspace{-.4em}%
			\strut%
			\BODY
			\vspace{-.4em}%
			\strut%
		}
	}
	\vspace{-0.4em}
	\par
}
\NewEnviron{InteractiveRead}{
	\noindent
	\normalsize
	\ttfamily
	\frenchspacing% to prevent extra spaces after punctuation. https://tex.stackexchange.com/q/118455/43242
	\framebox[0.55\textwidth][l]{%
		\parbox[t]{\textwidth}{
			\vspace{-.4em}%
			\strut%
			\BODY
			\vspace{-.4em}%
			\strut%
		}
	}
	\vspace{-0.4em}
	\par%
}

%-------------------------------------------------------------------------------
% The following are required for the overall layout:
%-------------------------------------------------------------------------------
\usepackage[english]{babel}
\usepackage{lmodern}
\usepackage{graphicx}
\usepackage{courier}
\usepackage[T1]{fontenc} % Standard
\usepackage[utf8]{inputenc} % UTF-8 support

%-------------------------------------------------------------------------------
% The following are required for most problems:
%-------------------------------------------------------------------------------
\usepackage{amsmath,amssymb}
\usepackage{wrapfig}
\usepackage{tikz}
\usepackage{enumitem}	% [noitemsep] for smaller lists
\usepackage{textcomp} % textquotesingle: '

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

\newcommand{\illustration}[3]{
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
