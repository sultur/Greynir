#!/usr/bin/env python3
"""

    Greynir: Natural language processing for Icelandic

    Grammar generator

    Copyright (C) 2023 Miðeind ehf.

       This program is free software: you can redistribute it and/or modify
       it under the terms of the GNU General Public License as published by
       the Free Software Foundation, either version 3 of the License, or
       (at your option) any later version.
       This program is distributed in the hope that it will be useful,
       but WITHOUT ANY WARRANTY; without even the implied warranty of
       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
       GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see http://www.gnu.org/licenses/.


    This tool reads in one or more grammar files and generates
    all possible sentences from the grammar.
    Uses algorithm from https://github.com/nltk/nltk/blob/develop/nltk/parse/generate.py
    The algorithm is modified to work with classes from GreynirEngine.
    Use --help to see more information on usage.

"""
from typing import (
    Callable,
    Iterable,
    Iterator,
    List,
    Optional,
    Union,
    Match,
)

import re
import sys
import itertools
from pathlib import Path
from functools import lru_cache

from islenska.basics import MarkOrder


# Hack to make this Python program executable from the tools subdirectory
basepath = Path(__file__).parent.resolve()
_UTILS = "tools"
if basepath.stem == _UTILS:
    sys.path.append(str(basepath.parent))


from islenska import Bin
from reynir.grammar import Nonterminal, Terminal
from reynir.binparser import BIN_Parser, BIN_LiteralTerminal

from queries import QueryGrammar

# TODO: Create random traversal functionality (itertools.dropwhile?)
# TODO: Allow replacing special terminals (no, sérnafn, lo, ...) with words
# TODO: Unwrap recursion (for dealing with complex recursive grammar items as in Greynir.grammar)

ColorF = Callable[[str], str]
_reset: str = "\033[0m"
bold: ColorF = lambda s: f"\033[01m{s}{_reset}"
black: ColorF = lambda s: f"\033[30m{s}{_reset}"
red: ColorF = lambda s: f"\033[31m{s}{_reset}"
green: ColorF = lambda s: f"\033[32m{s}{_reset}"
orange: ColorF = lambda s: f"\033[33m{s}{_reset}"
blue: ColorF = lambda s: f"\033[34m{s}{_reset}"
purple: ColorF = lambda s: f"\033[35m{s}{_reset}"
cyan: ColorF = lambda s: f"\033[36m{s}{_reset}"
lightgrey: ColorF = lambda s: f"\033[37m{s}{_reset}"
darkgrey: ColorF = lambda s: f"\033[90m{s}{_reset}"
lightred: ColorF = lambda s: f"\033[91m{s}{_reset}"
lightgreen: ColorF = lambda s: f"\033[92m{s}{_reset}"
yellow: ColorF = lambda s: f"\033[93m{s}{_reset}"
lightblue: ColorF = lambda s: f"\033[94m{s}{_reset}"
pink: ColorF = lambda s: f"\033[95m{s}{_reset}"
lightcyan: ColorF = lambda s: f"\033[96m{s}{_reset}"

# Grammar item type
_GIType = Union[Nonterminal, Terminal]
# BÍN, for word lookups
BIN = Bin()

# Mebibyte
MiB = 1024 * 1024

# Preamble hack in case we aren't testing a query grammar
# (prevents an error in the QueryGrammar class)
PREAMBLE = """
QueryRoot → Query

Query → ""

"""

# Word categories which should have some variant specified
_STRICT_CATEGORIES = frozenset(
    (
        "no",
        "kk",
        "kvk",
        "hk",
        "so",
        "lo",
        "fn",
        "pfn",
        "gr",
        "rt",
        "to",
    )
)


@lru_cache(maxsize=500)  # VERY useful cache
def get_wordform(gi: BIN_LiteralTerminal) -> str:
    """
    Fetch all possible wordforms for a literal terminal
    specification and return as readable string.
    """
    global strict
    word, cat, variants = gi.first, gi.category, "".join(gi.variants).casefold()
    bin_entries = BIN.lookup_lemmas(word)[1]

    if strict:
        # Strictness checks on usage of
        # single-quoted terminals in the grammar
        assert (
            len(bin_entries) > 0
        ), f"Meaning not found, use root of word for: {gi.name}"
        assert (
            cat is not None
        ), f"Specify category for single quoted terminal: {gi.name}"
        # Filter by word category
        assert len(list(filter(lambda m: m.ofl == cat, bin_entries))) < 2, (
            "Category not specific enough, "
            "single quoted terminal has "
            f"multiple possible categories: {gi.name}"
        )
        if cat in _STRICT_CATEGORIES:
            assert (
                len(variants) > 0
            ), f"Specify variants for single quoted terminal: {gi.name}"

    if not cat and len(bin_entries) > 0:
        # Guess category from lemma lookup
        cat = bin_entries[0].ofl

    wordforms = BIN.lookup_variants(
        word,
        cat or "",
        variants or "",
    )

    if len(wordforms) == 0:
        # BÍN can't find variants, weird word,
        # use double-quotes
        return red(gi.name)
    if len(wordforms) == 1:
        # Author of grammar should probably use double-quotes
        # (except if this is due to backslash specification, like /fall)
        return yellow(wordforms[0].bmynd)
    if len(set(wf.bmynd for wf in wordforms)) == 1:
        # All variants are the same here,
        # author of grammar should maybe use double-quotes instead
        return lightred(f"({'|'.join(wf.bmynd for wf in wordforms)})")

    # Sort wordforms in a canonical order
    wordforms.sort(key=lambda ks: MarkOrder.index(ks.ofl, ks.mark))

    # Join all matched wordforms together (within parenthesis)
    return lightcyan(f"({'|'.join(wf.bmynd for wf in wordforms)})")


def _break_up_line(line: List[str], break_indices: List[int]) -> Iterable[List[str]]:
    """
    Breaks up a single line containing parenthesized word forms
    and yields lines with all combinations of the word forms.
    """
    for comb in itertools.product(
        *[set(line[i].lstrip("(").rstrip(")").split("|")) for i in break_indices]
    ):
        yield [
            comb[break_indices.index(i)] if i in break_indices else line[i]
            for i in range(len(line))
        ]


def expander(it: Iterable[List[str]]) -> Iterable[List[str]]:
    """
    Expand lines in iterator that include (word form 1|word form 2|...) items.
    """
    for line in it:
        paren_indices = [
            i
            for i, w in enumerate(line)
            if w.startswith("(") and w.endswith(")")
            # ^ We can do this as ansi color is disabled when fully expanding lines
        ]
        if paren_indices:
            yield from _break_up_line(line, paren_indices)
        else:
            yield line


def generate_from_cfg(
    grammar: QueryGrammar,
    *,
    root: Optional[Union[Nonterminal, str]] = None,
    depth: Optional[int] = None,
    n: Optional[int] = None,
    expand: Optional[bool] = False,
) -> Iterable[str]:
    """
    Generates an iterator of all sentences from
    a context free grammar.
    """

    if root is None:
        root = grammar.root
    elif isinstance(root, str):
        root = grammar.nonterminals.get(root)
    assert (
        root is not None and root in grammar.nt_dict
    ), "Invalid root, make sure it exists in the grammar"

    if depth is None:
        depth = sys.maxsize // 2

    assert depth is not None, "Invalid depth"
    assert 0 < depth <= sys.maxsize, f"Depth must be in range 1 - {sys.maxsize}"

    if (
        len(grammar.nt_dict[root][0][1]._rhs) == 1  # type: ignore
        and grammar.nt_dict[root][0][1]._rhs[0].name == '""'  # type: ignore
    ):
        # Remove hack empty (Query -> "") production
        grammar.nt_dict[root].pop(0)

    iter: Iterable[List[str]] = itertools.chain.from_iterable(
        _generate_all(
            grammar,
            pt[1]._rhs,  # type: ignore
            depth,
        )
        for pt in grammar.nt_dict[root]
    )

    if expand:
        # Expand condensed lines
        # (containing parenthesized word forms)
        # into separate lines
        iter = expander(iter)

    # n=None means return all sentences,
    # otherwise return n sentences
    iter = itertools.islice(iter, 0, n)

    return (" ".join(sl) for sl in iter)


def _generate_all(
    grammar: QueryGrammar, items: List[_GIType], depth: int
) -> Iterator[List[str]]:
    if items:
        try:
            if items[0].name == "'?'?" and len(items) == 1:
                # Skip the optional final question mark
                # (common in query grammars)
                yield []
            else:
                for frag1 in _generate_one(grammar, items[0], depth):
                    for frag2 in _generate_all(grammar, items[1:], depth):
                        yield frag1 + frag2
        except RecursionError:
            raise RecursionError(
                "The grammar has a rule that yields infinite recursion!\n"
                "Try running again with a smaller max depth set.\n"
                f"Depth: {depth}.\nCurrent nonterminal: {items[0]}"
            )
    else:
        yield []


# Recursive nonterminals raise a recursion error,
# match them with this regex and skip traversal
# (note: there are probably more recursive
# nonterminals, they can be added here)
_RECURSIVE_NT = re.compile(r"^Nl([/_][a-zA-Z0-9]+)*$")
_PLACEHOLDER_RE = re.compile(r"{([\w]+?)}")
_PLACEHOLDER_PREFIX = "GENERATORPLACEHOLDER_"
_PLACEHOLDER_PREFIX_LEN = len(_PLACEHOLDER_PREFIX)


def _generate_one(
    grammar: QueryGrammar, gi: _GIType, depth: int
) -> Iterator[List[str]]:
    if depth > 0:
        if _RECURSIVE_NT.fullmatch(gi.name):
            # Special handling of Nl nonterminal,
            # since it is recursive
            yield [pink(f"<{gi.name}>")]
        elif gi.name.startswith(_PLACEHOLDER_PREFIX):
            # Placeholder nonterminal (replaces)
            yield [blue(f"{{{gi.name[_PLACEHOLDER_PREFIX_LEN:]}}}")]
        elif isinstance(gi, Nonterminal):
            if gi.is_optional and gi.name.endswith("*"):
                # Star nonterminal, signify using brackets and '...'
                prod = grammar.nt_dict[gi][0][1]
                gi = prod._rhs[-1]  # type: ignore
                # Literal text if gi is terminal,
                # otherwise surround nonterminal name with curly brackets
                t = gi.literal_text or f"{{{gi.name}}}"
                yield [purple(f"[{t} ...]")]
            else:
                # Nonterminal, fetch its productions
                for pt in grammar.nt_dict[gi]:
                    yield from _generate_all(
                        grammar,
                        pt[1]._rhs,  # type: ignore
                        depth - 1,
                    )
        else:
            if isinstance(gi, BIN_LiteralTerminal):
                lit = gi.literal_text
                if lit:
                    yield [lit]
                else:
                    yield [get_wordform(gi)]
            else:
                # Special nonterminals such as no, sérnafn, töl, ...
                yield [green(f"<{gi.name}>")]
    else:
        yield [lightblue(f"{{{gi.name}}}")]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generates sentences from a context free grammar."
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="file/s containing the grammar fragments. "
        "Always loads Greynir.grammar, so no file has to be specified "
        "when generating sentences from Greynir.grammar",
    )
    parser.add_argument(
        "-r",
        "--root",
        default="Query",
        help="root nonterminal to start from",
    )
    parser.add_argument(
        "-d",
        "--depth",
        type=int,
        help="maximum depth of the generated sentences",
    )
    parser.add_argument(
        "-n",
        "--num",
        type=int,
        help="maximum number of sentences to generate",
    )
    parser.add_argument(
        "-e",
        "--expand",
        action="store_true",
        help="expand lines with multiple interpretations into separate lines",
    )
    parser.add_argument(
        "-s",
        "--strict",
        action="store_true",
        help="enable strict mode, adds some opinionated assertions about the grammar",
    )
    parser.add_argument(
        "-c",
        "--color",
        action="store_true",
        help="enables colored output, when not fully "
        "expanding lines or writing output to file",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="write output to file instead of stdout (faster)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="forcefully overwrite output file, ignoring any warnings",
    )
    parser.add_argument("--max-size", type=int, help="Maximum output filesize in MiB.")
    args = parser.parse_args()

    strict = args.strict

    if args.num:
        args.num += 1

    output = sys.stdout
    p: Optional[Path] = None
    if args.output:
        p = args.output
        assert isinstance(p, Path)
        if (p.is_file() or p.exists()) and not args.force:
            print("Output file already exists!")
            exit(1)

    # Expand and writing to file disables color
    args.color = args.color and not args.expand and p is None

    if not args.color:
        useless: ColorF = lambda s: s
        # Undefine color functions
        [
            bold,
            black,
            red,
            green,
            orange,
            blue,
            purple,
            cyan,
            lightgrey,
            darkgrey,
            lightred,
            lightgreen,
            yellow,
            lightblue,
            pink,
            lightcyan,
        ] = [useless] * 16

    grammar_fragments: str = PREAMBLE

    # We replace {...} format strings with a placeholder
    placeholder_defs: str = ""

    def placeholder_func(m: Match[str]) -> str:
        """
        Replaces {...} format strings in grammar with an empty nonterminal.
        We then handle these nonterminals specifically in _generate_one().
        """
        global placeholder_defs
        new_nt = f"{_PLACEHOLDER_PREFIX}{m.group(1)}"
        # Create empty production for this nonterminal ('keep'-tag just in case)
        placeholder_defs += f"\n{new_nt} → ∅\n$tag(keep) {new_nt}\n"
        # Replace format string with reference to new nonterminal
        return new_nt

    for file in [BIN_Parser._GRAMMAR_FILE] + args.files:  # type: ignore
        with open(file, "r") as f:
            grammar_fragments += "\n"
            grammar_fragments += _PLACEHOLDER_RE.sub(placeholder_func, f.read())

    # Add all the placeholder nonterminal definitions we added
    grammar_fragments += placeholder_defs
    if len(args.files) == 0:
        # Generate Greynir.grammar by default
        grammar_fragments = grammar_fragments.replace('Query → ""', "Query → S0", 1)

    # Initialize QueryGrammar class from grammar files
    grammar = QueryGrammar()
    grammar.read_from_generator(
        args.files[0] if args.files else BIN_Parser._GRAMMAR_FILE,  # type: ignore
        iter(grammar_fragments.split("\n")),
    )

    # Create sentence generator
    g = generate_from_cfg(
        grammar,
        root=args.root,
        depth=args.depth,
        n=args.num,
        expand=args.expand,
    )

    if p is not None:
        # Writing to file
        with p.open("w") as f:
            if args.max_size:
                max_size = args.max_size * MiB
                for sentence in g:
                    print(sentence, file=f)
                    if f.tell() >= max_size:
                        break
            else:
                for sentence in g:
                    print(sentence, file=f)
    else:
        # Writing to stdout
        try:
            for sentence in g:
                print(sentence)
        finally:
            # Just in case an error is raised
            # before terminal color is reset
            if args.color:
                print(_reset, end="")
