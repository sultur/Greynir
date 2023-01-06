"""

    Greynir: Natural language processing for Icelandic

    Query module

    Copyright (C) 2022 Miðeind ehf.

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


    This module implements a query processor that operates on queries
    in the form of parse trees and returns the results requested,
    if the query is valid and understood.

"""

from typing import (
    ChainMap as ChainMapType,
    DefaultDict,
    Optional,
    Sequence,
    Set,
    Tuple,
    List,
    Dict,
    Callable,
    Iterator,
    Iterable,
    Union,
    Any,
    Mapping,
    cast,
)
from typing_extensions import Protocol

from types import FunctionType, ModuleType

import importlib
import logging
from copy import deepcopy
from datetime import datetime, timedelta
import json
import re
import random
from collections import defaultdict, ChainMap
from itertools import takewhile

from settings import Settings

from db import SessionContext, Session, desc
from db.models import Query as QueryRow
from db.models import QueryData, QueryLog
from queries.extras.dialogue import (
    DialogueStateManager as DSM,
)

from reynir import TOK, Tok, tokenize, correct_spaces
from reynir.fastparser import (
    Fast_Parser,
    ParseForestDumper,
    ParseError,
    ffi,  # type: ignore
)
from tokenizer import BIN_Tuple
from reynir.binparser import BIN_Grammar, BIN_Token
from reynir.reducer import (
    NULL_SC,
    ChildDict,
    KeyTuple,
    ParseForestReducer,
    Reducer,
    ResultDict,
    ScoreDict,
)
from reynir.bindb import GreynirBin
from reynir.fastparser import Node as SPPF_Node
from reynir.grammar import GrammarError, Nonterminal
from islenska.bindb import BinFilterFunc

from tree import ProcEnv, Tree, TreeStateDict, Node, Result

# from nertokenizer import recognize_entities
from images import get_image_url
from utility import QUERIES_DIR, modules_in_dir, QUERIES_UTIL_DIR
from geo import LatLonTuple


# Query response
ResponseDict = Dict[str, Any]
ResponseMapping = Mapping[str, Any]
ResponseType = Union[ResponseDict, List[ResponseDict]]

# Query context
ContextDict = Dict[str, Any]

# Client data
ClientDataDict = Dict[str, Union[str, int, float, bool, Dict[str, str]]]

# Answer tuple (corresponds to parameter list of Query.set_answer())
AnswerTuple = Tuple[ResponseType, str, Optional[str]]

LookupFunc = Callable[[str], Tuple[str, List[BIN_Tuple]]]

HelpFunc = Callable[[str], str]


class QueryStateDict(TreeStateDict):
    query: "Query"
    names: Dict[str, str]


class CastFunc(Protocol):
    def __call__(self, w: str, *, filter_func: Optional[BinFilterFunc] = None) -> str:
        ...


# The grammar root nonterminal for queries; see Greynir.grammar in GreynirPackage
_QUERY_ROOT = "QueryRoot"

# A fixed preamble that is inserted before the concatenated query grammar fragments
_GRAMMAR_PREAMBLE = """

QueryRoot →
    Query

# Mark the QueryRoot nonterminal as a root in the grammar
$root(QueryRoot)

# Keep all child families of Query, i.e. all possible query
# trees, rather than just the highest-scoring one

$tag(no_reduce) Query

"""

# Query prefixes that we cut off before further processing
# The 'bæjarblað'/'hæðarblað' below is a common misunderstanding by the Google ASR
_IGNORED_QUERY_PREFIXES = (
    "embla",
    "hæ embla",
    "hey embla",
    "sæl embla",
    "bæjarblað",
    "hæðarblað",
)
_IGNORED_PREFIX_RE = r"^({0})\s*".format("|".join(_IGNORED_QUERY_PREFIXES))
# Auto-capitalization corrections
_CAPITALIZATION_REPLACEMENTS = (("í Dag", "í dag"),)


def beautify_query(query: str) -> str:
    """Return a minimally beautified version of the given query string"""
    # Make sure the query starts with an uppercase letter
    bq = (query[0].upper() + query[1:]) if query else ""
    # Add a question mark if no other ending punctuation is present
    if not any(bq.endswith(s) for s in ("?", ".", "!")):
        bq += "?"
    return bq


class QueryGrammar(BIN_Grammar):

    """A subclass of BIN_Grammar that reads its input from
    strings obtained from query handler plug-ins in the
    queries subdirectory, prefixed by a preamble"""

    def __init__(self) -> None:
        super().__init__()
        # Enable the 'include_queries' condition
        self.set_conditions({"include_queries"})

    @classmethod
    def is_grammar_modified(cls) -> bool:
        """Override inherited function to specify that query grammars
        should always be reparsed, since the set of plug-in query
        handlers may have changed, as well as their grammar fragments."""
        return True

    def read(
        self, fname: str, verbose: bool = False, binary_fname: Optional[str] = None
    ) -> None:
        """Overrides the inherited read() function to supply grammar
        text from a file as well as additional grammar fragments
        from query processor modules."""

        def grammar_generator() -> Iterator[str]:
            """A generator that yields a grammar file, line-by-line,
            followed by grammar additions coming from a string
            that has been coalesced from grammar fragments in query
            processor modules."""
            with open(fname, "r", encoding="utf-8") as inp:
                # Read grammar file line-by-line
                for line in inp:
                    yield line
            # Yield the query grammar preamble
            grammar_preamble = _GRAMMAR_PREAMBLE.split("\n")
            for line in grammar_preamble:
                yield line
            # Yield grammar additions from plug-ins, if any
            grammar_additions = QueryParser.grammar_additions().split("\n")
            for line in grammar_additions:
                yield line

        try:
            # Note that if Settings.DEBUG is True, we always write a fresh
            # binary grammar file, regardless of file timestamps. This helps
            # in query development, as query grammar fragment strings may change
            # without any .grammar source file change (which is the default
            # trigger for generating new binary grammar files).
            self.read_from_generator(
                fname,
                grammar_generator(),
                verbose,
                binary_fname,
                force_new_binary=Settings.DEBUG,
            )
        except (IOError, OSError):
            raise GrammarError("Unable to open or read grammar file", fname, 0)


class BannedForestException(Exception):
    ...


_BANNED_RD: ResultDict = cast(ResultDict, {"sc": 0, "ban": True})


class QueryParseForestReducer(ParseForestReducer):
    def __init__(self, grammar: BIN_Grammar, scores: ScoreDict, query: "Query"):
        super().__init__(grammar, scores)
        self._q = query

    def go(self, root_node: SPPF_Node) -> ResultDict:
        """Perform the reduction"""
        # Memoization/caching dict, keyed by node and memoization key
        visited: Dict[KeyTuple, ResultDict] = dict()
        # Current memoization key
        current_key = 0
        # Next memoization key to use
        next_key = 0

        def calc_score(w: SPPF_Node) -> ResultDict:
            """Navigate from (w, current_key) where w is a node and current_key
            is an integer navigation key, carefully controlling the memoization
            of already visited nodes.
            """
            nonlocal current_key, next_key
            # Has this (node, current_key) tuple been memoized?
            v = visited.get((w, current_key))
            if v is not None:
                # Yes: return the previously calculated result
                return v

            # Is this nonterminal banned for this specific query?
            if w.nonterminal and self._q.is_nonterminal_banned(w.nonterminal):
                # Yes: return ResultDict with ban set to True
                return _BANNED_RD

            # We have not seen this (node, current_key) combination before:
            # reduce it, calculate its score and memoize it
            if w._token is not None:
                # Return the score of this terminal option
                v = self.visit_token(w)
            elif w.is_span and w._families:
                # We have a nonempty nonterminal node with one or more families
                # of children, i.e. multiple possible derivations
                child_scores: ChildDict = defaultdict(lambda: {"sc": 0})
                # Go through each family and calculate its score
                for fam_ix, (prod, children) in enumerate(w._families):
                    # Initialize the score of this family of children, so that productions
                    # with higher priorities (more negative prio values) get a starting bonus
                    child_scores[fam_ix]["sc"] = -10 * prod.priority
                    for ch in children:
                        if ch is not None:
                            rd = calc_score(ch)
                            d = child_scores[fam_ix]
                            if "ban" in rd:
                                # If this child/family is completely banned,
                                # carry its ban status on up into child_scores dict
                                d["ban"] = rd["ban"]  # type: ignore
                            else:  # Otherwise modify score
                                d["sc"] += rd["sc"]
                            # Carry information about contained verbs ("so") up the tree
                            for key in ("so", "sl"):
                                if key in rd:
                                    if key in d:
                                        d[key].extend(rd[key])  # type: ignore
                                    else:
                                        d[key] = rd[key][:]  # type: ignore

                if not child_scores:
                    # Empty node
                    return NULL_SC

                nt: Optional[Nonterminal] = w.nonterminal if w.is_completed else None
                if len(child_scores) == 1:
                    # Not ambiguous: only one result, do a shortcut
                    # Will raise an exception if not exactly one value
                    [v] = child_scores.values()
                else:
                    # Eliminate all families except the best scoring one
                    # Sort by ban-status (non-banned first),
                    # then score in decreasing order,
                    # and then using the family index
                    # as a tie-breaker for determinism
                    s = sorted(
                        child_scores.items(),
                        key=lambda x: (
                            0 if x[1].get("ban") else 1,  # Non-banned first
                            x[1]["sc"],  # Score (descending)
                            -x[0],  # Index (for determinism)
                        ),
                        reverse=True,
                    )

                    if not s[0][1].get("ban") and s[-1][1].get("ban"):
                        # We have a blend of non-banned and banned families,
                        # prune the banned ones (even for no-reduce nonterminals)
                        w._families = [
                            w._families[x[0]]
                            for x in takewhile(lambda y: not y[1].get("ban"), s)
                        ]

                    # This is the best scoring family
                    # (and the one with the lowest index
                    # if there are many with the same score)
                    ix, v = s[0]

                    # Note: at this point the best scoring family
                    # might be banned or not, we deal with this issue
                    # when returning the root score from go()

                    # If the node nonterminal is marked as "no_reduce",
                    # we leave the child families in place. This feature
                    # is used in query processing.
                    if nt is None or not nt.no_reduce:
                        # And now for the key action of the reducer:
                        # Eliminate all other families
                        w.reduce_to(ix)

                if nt is not None:
                    # We will be adjusting the result: make sure we do so on
                    # a separate dict copy (we don't want to clobber the child's dict)
                    # Get score adjustment for this nonterminal, if any
                    # (This is the $score(+/-N) pragma from Greynir.grammar)
                    v["sc"] += self._score_adj.get(nt, 0)

                # The winning family is now the only remaining family
                # of children of this node; the others have been culled.
            else:
                v = NULL_SC
            # Memoize the result for this (node, current_key) combination
            visited[(w, current_key)] = v
            w.score = v["sc"]
            return v

        # Start the scoring and reduction process at the root
        if root_node is None:
            return NULL_SC

        root_score = calc_score(root_node)
        if root_score.get("ban"):
            # Best family is banned, which means that
            # no non-banned families were found
            raise BannedForestException("Entire parse forest for this query is banned")
        return root_score


class QueryReducer(Reducer):
    def __init__(self, grammar: BIN_Grammar, query: "Query"):
        self._grammar = grammar
        self._q = query

    def _reduce(self, w: SPPF_Node, scores: ScoreDict) -> ResultDict:
        """Reduce a forest with a root in w based on subtree scores"""
        return QueryParseForestReducer(self._grammar, scores, self._q).go(w)


class QueryParser(Fast_Parser):

    """A subclass of Fast_Parser, specialized to parse queries"""

    # Override the punctuation that is understood by the parser,
    # adding the forward slash ('/')
    _UNDERSTOOD_PUNCTUATION = BIN_Token._UNDERSTOOD_PUNCTUATION + "+/"

    _GRAMMAR_BINARY_FILE = Fast_Parser._GRAMMAR_FILE + ".query.bin"

    # Keep a separate grammar class instance and time stamp for
    # QueryParser. This Python sleight-of-hand overrides
    # class attributes that are defined in BIN_Parser, see binparser.py.
    _grammar_ts: Optional[float] = None
    _grammar: Optional[QueryGrammar] = None
    _grammar_class = QueryGrammar

    # Also keep separate class instances of the C grammar and its timestamp
    _c_grammar: Any = cast(Any, ffi).NULL
    _c_grammar_ts: Optional[float] = None

    # Store the grammar additions for queries
    # (these remain constant for all query parsers, so there is no
    # need to store them per-instance)
    _grammar_additions = ""

    def __init__(self, grammar_additions: str) -> None:
        QueryParser._grammar_additions = grammar_additions
        super().__init__(verbose=False, root=_QUERY_ROOT)

    @classmethod
    def grammar_additions(cls) -> str:
        return cls._grammar_additions


class QueryTree(Tree):

    """Extend the tree.Tree class to collect all child families of the
    Query nonterminal from a query parse forest"""

    def __init__(self):
        super().__init__()
        self._query_trees: List[Node] = []

    def handle_O(self, n: int, s: str) -> None:
        """Handle the O (option) tree record"""
        assert n == 1

    def handle_Q(self, n: int) -> None:
        """Handle the Q (final) tree record"""
        super().handle_Q(n)
        # Access the QueryRoot node
        root = self.s[1]
        # Access the Query node
        query = None if root is None else root.child
        # The child nodes of the Query node are the valid query parse trees
        self._query_trees = [] if query is None else list(query.children())

    @property
    def query_trees(self) -> List[Node]:
        """Returns the list of valid query parse trees, i.e. child nodes of Query"""
        return self._query_trees

    @property
    def query_nonterminals(self) -> Set[str]:
        """Return the set of query nonterminals that match this query"""
        return set(node.string_self() for node in self._query_trees)

    def process_queries(
        self, query: "Query", session: Session, processor: ProcEnv
    ) -> bool:
        """Process all query trees that the given processor is interested in"""
        processor_query_types: Set[str] = processor.get("QUERY_NONTERMINALS", set())
        # Every tree processor must be interested in at least one query type
        assert isinstance(processor_query_types, set)
        # For development, we allow processors to be disinterested in any query
        # assert len(processor_query_types) > 0
        if self.query_nonterminals.isdisjoint(processor_query_types):
            # But this processor is not interested in any of the nonterminals
            # in this query's parse forest: don't waste more cycles on it
            return False

        # Prepare dialogue state manager before processing
        dialogue_name: Optional[str] = getattr(processor, "DIALOGUE_NAME", None)
        if dialogue_name:
            query.dsm.prepare_dialogue(dialogue_name)

        with self.context(session, processor, query=query) as state:
            for query_tree in self._query_trees:
                print(
                    "Processing query tree",
                    query_tree.string_self(),
                    "in module",
                    processor["__name__"],
                )
                # Is the processor interested in the root nonterminal
                # of this query tree?
                if query_tree.string_self() in processor_query_types:
                    # Hand the query tree over to the processor
                    self.process_sentence(state, query_tree)
                    if query.has_answer():
                        # The processor successfully answered the query: We're done
                        if dialogue_name:
                            # Update dialogue data if appropriate
                            # TODO: This should be hidden within the dsm.get_answer
                            query.dsm.update_dialogue_data()
                        return True
        return False


def _merge_two_dicts(dict_a: Dict[str, Any], dict_b: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge two dicts,
    updating dict_a with values from dict_b,
    leaving other values intact.
    """
    for key in dict_b:
        if (
            key in dict_a
            and isinstance(dict_a[key], dict)
            and isinstance(dict_b[key], dict)
        ):
            _merge_two_dicts(dict_a[key], dict_b[key])
        else:
            dict_a[key] = dict_b[key]
    return dict_a


class Query:

    """A Query is initialized by parsing a query string using QueryRoot as the
    grammar root nonterminal. The Query can then be executed by processing
    the best parse tree using the nonterminal handlers given above, returning a
    result object if successful."""

    # Processors that handle parse trees
    _tree_processors: List[ProcEnv] = []
    # Functions from utility modules,
    # facilitating code reuse between query modules
    _utility_functions: ChainMapType[str, FunctionType] = ChainMap()
    # Handler functions within processors that handle plain text
    _text_processors: List[Callable[["Query"], bool]] = []
    # Singleton instance of the query parser
    _parser: Optional[QueryParser] = None
    # Help texts associated with lemmas
    _help_texts: Dict[str, List[HelpFunc]] = dict()

    def __init__(
        self,
        session: Session,  # SQLAlchemy session
        query: str,
        voice: bool,
        auto_uppercase: bool,
        location: Optional[LatLonTuple],
        client_id: Optional[str],
        client_type: Optional[str],
        client_version: Optional[str],
    ) -> None:

        self._query = q = self._preprocess_query_string(query)
        self._session = session
        self._location = location
        # Prepare a "beautified query" string that can be
        # shown in a client user interface. By default, this
        # starts with an uppercase letter and ends with a
        # question mark, but this can be modified during the
        # processing of the query.
        self.set_beautified_query(beautify_query(q))
        # Boolean flag for whether this is a voice query
        self._voice = voice
        self._auto_uppercase = auto_uppercase
        self._error: Optional[str] = None
        # A detailed answer, which can be a list or a dict
        self._response: Optional[ResponseType] = None
        # A single "best" displayable text answer
        self._answer: Optional[str] = None
        # A version of self._answer that can be
        # fed to a voice synthesizer
        self._voice_answer: Optional[str] = None
        self._tree: Optional[QueryTree] = None
        self._qtype: Optional[str] = None
        self._key: Optional[str] = None
        self._toklist: Optional[List[Tok]] = None
        # Expiration timestamp, if any
        self._expires: Optional[datetime] = None
        # URL assocated with query, can be set by query response handler
        # and subsequently provided to the remote client
        self._url: Optional[str] = None
        # Command returned by query
        self._command: Optional[str] = None
        # Image URL returned by query
        self._image: Optional[str] = None
        # Client id, if known
        self._client_id = client_id
        # Client type, if known
        self._client_type = client_type
        # Client version, if known
        self._client_version = client_version
        # Source of answer to query
        self._source: Optional[str] = None
        # Query context, which is None until fetched via self.fetch_context()
        # This should be a dict that can be represented in JSON
        self._context: Optional[ContextDict] = None
        # Banned nonterminals for this query,
        # dynamically generated from query modules
        self._banned_nonterminals: Set[str] = set()
        # The dialogue state manager, used for dialogue modules
        self._dsm: DSM = DSM(self._client_id, self._session)

    def _preprocess_query_string(self, q: str) -> str:
        """Preprocess the query string prior to further analysis"""
        if not q:
            return q
        qf = re.sub(_IGNORED_PREFIX_RE, "", q, flags=re.IGNORECASE)
        # Remove " embla" suffix, if present
        qf = re.sub(r"\s+embla$", "", qf, flags=re.IGNORECASE)
        # Fix common Google ASR mistake: 'hæ embla' is returned as 'bæjarblað'
        if not qf and q == "bæjarblað":
            q = "hæ embla"
        # If stripping the prefixes results in an empty query,
        # just return original query string unmodified.
        return qf or q

    @classmethod
    def init_class(cls) -> None:
        """Initialize singleton data, i.e. the list of query
        processor modules and the query parser instance"""
        all_procs: List[ModuleType] = []
        tree_procs: List[Tuple[int, ModuleType]] = []
        text_procs: List[Tuple[int, Callable[["Query"], bool]]] = []

        # Load the query processor modules found in the
        # queries directory. The modules can be tree and/or text processors,
        # and we sort them into two lists, accordingly.
        modnames = modules_in_dir(QUERIES_DIR)
        for modname in sorted(modnames):
            try:
                m = importlib.import_module(modname)
                is_proc = False
                # Obtain module priority, if any
                priority: int = getattr(m, "PRIORITY", 0)
                if getattr(m, "HANDLE_TREE", False):
                    # This is a tree processor
                    is_proc = True
                    tree_procs.append((priority, m))
                handle_plain_text = getattr(m, "handle_plain_text", None)
                if handle_plain_text is not None:
                    # This is a text processor:
                    # store a reference to its handler function
                    is_proc = True
                    text_procs.append((priority, handle_plain_text))
                if is_proc:
                    all_procs.append(m)
            except ImportError as e:
                logging.error(
                    "Error importing query processor module {0}: {1}".format(modname, e)
                )
        # Sort the processors by descending priority
        # so that the higher-priority ones get invoked bfore the lower-priority ones
        # We create a ChainMap (processing environment) for each tree processor,
        # containing the processors attributes with the utility modules as a fallback
        cls._tree_processors = [
            cls.create_processing_env(t[1])
            for t in sorted(tree_procs, key=lambda x: -x[0])
        ]
        cls._text_processors = [t[1] for t in sorted(text_procs, key=lambda x: -x[0])]

        # Obtain query grammar fragments from the utility modules and tree processors
        grammar_fragments: List[str] = []

        # Load utility modules
        modnames = modules_in_dir(QUERIES_UTIL_DIR)
        for modname in sorted(modnames):
            try:
                um = importlib.import_module(modname)
                exported = vars(um)  # Get all exported values from module

                # Pop grammar fragment, if any
                fragment = exported.pop("GRAMMAR", None)
                if fragment and isinstance(fragment, str):
                    # This utility module has a grammar fragment,
                    # and probably corresponding nonterminal functions
                    # We add the grammar fragment to our grammar
                    grammar_fragments.append(fragment)
                    # and the nonterminal functions to the shared functions ChainMap,
                    # ignoring non-callables and underscore (private) attributes
                    cls._utility_functions.update(
                        (
                            (k, v)
                            for k, v in exported.items()
                            if callable(v) and not k.startswith("_")
                        )
                    )
            except ImportError as e:
                logging.error(
                    "Error importing utility module {0}: {1}".format(modname, e)
                )

        for processor in cls._tree_processors:
            # Check whether this dialogue/tree processor supplies a query grammar fragment
            fragment = processor.pop("GRAMMAR", None)
            if fragment and isinstance(fragment, str):
                # Looks legit: add it to our list
                grammar_fragments.append(fragment)

        # Collect topic lemmas that can be used to provide
        # context-sensitive help texts when queries cannot be parsed
        help_texts: DefaultDict[str, List[HelpFunc]] = defaultdict(list)
        for processor in all_procs:
            # Collect topic lemmas and corresponding help text functions
            topic_lemmas = getattr(processor, "TOPIC_LEMMAS", None)
            if topic_lemmas:
                help_text_func = getattr(processor, "help_text", None)
                # If topic lemmas are given, a help_text function
                # should also be present
                assert help_text_func is not None
                if help_text_func is not None:
                    for lemma in topic_lemmas:
                        help_texts[lemma].append(help_text_func)
        cls._help_texts = help_texts

        # Coalesce the grammar additions from the fragments
        grammar_additions = "\n".join(grammar_fragments)
        # Initialize a singleton parser instance for queries,
        # with the nonterminal 'QueryRoot' as the grammar root
        cls._parser = QueryParser(grammar_additions)

    @staticmethod
    def create_processing_env(processor: ModuleType) -> ProcEnv:
        """
        Create a new child of the utility functions ChainMap.
        Returns a mapping suitable for parsing query trees,
        where the current processor's functions are prioritized over
        the shared utility module functions.
        """
        return Query._utility_functions.new_child(vars(processor))

    def _parse(self, toklist: Iterable[Tok]) -> Tuple[ResponseDict, Dict[int, str]]:
        """Parse a token list as a query"""
        bp = Query._parser
        assert bp is not None
        num_sent = 0
        num_parsed_sent = 0
        rdc = QueryReducer(bp.grammar, self)
        trees: Dict[int, str] = dict()
        sent: List[Tok] = []

        for t in toklist:
            if t[0] == TOK.S_BEGIN:
                if num_sent > 0:
                    # A second sentence is beginning: this is not valid for a query
                    raise ParseError("A query cannot contain more than one sentence")
                sent = []
            elif t[0] == TOK.S_END:
                slen = len(sent)
                if not slen:
                    continue
                num_sent += 1
                # Parse the accumulated sentence
                num = 0
                try:
                    # Parse the sentence
                    forest = bp.go(sent)
                    if forest is not None:
                        num = Fast_Parser.num_combinations(forest)
                        if num > 1:
                            # Reduce the resulting forest
                            forest = rdc.go(forest)
                except (ParseError, BannedForestException):
                    forest = None
                    num = 0
                if num > 0:
                    num_parsed_sent += 1
                    # Obtain a text representation of the parse tree
                    assert forest is not None
                    trees[num_sent] = ParseForestDumper.dump_forest(forest)

            elif t[0] == TOK.P_BEGIN:
                pass
            elif t[0] == TOK.P_END:
                pass
            else:
                sent.append(t)
        result: ResponseDict = dict(num_sent=num_sent, num_parsed_sent=num_parsed_sent)
        return result, trees

    @staticmethod
    def _query_string_from_toklist(toklist: Iterable[Tok]) -> str:
        """Re-create a query string from an auto-capitalized token list"""
        actual_q = correct_spaces(" ".join(t.txt for t in toklist if t.txt))
        if actual_q:
            # Fix stuff that the auto-capitalization tends to get wrong,
            # such as 'í Dag'
            for wrong, correct in _CAPITALIZATION_REPLACEMENTS:
                actual_q = actual_q.replace(wrong, correct)
            # Capitalize the first letter of the query
            actual_q = actual_q[0].upper() + actual_q[1:]
            # Terminate the query with a question mark,
            # if not otherwise terminated
            if not any(actual_q.endswith(s) for s in ("?", ".", "!")):
                actual_q += "?"
        return actual_q

    def parse(self, result: ResponseDict) -> bool:
        """Parse the query from its string, returning True if valid"""
        self._tree = None  # Erase previous tree, if any
        self._error = None  # Erase previous error, if any
        self._qtype = None  # Erase previous query type, if any
        self._key = None
        self._toklist = None

        q = self._query
        if not q:
            self.set_error("E_EMPTY_QUERY")
            return False

        # Tokenize and auto-capitalize the query string, without multiplying numbers together
        toklist = list(
            tokenize(
                q,
                auto_uppercase=self._auto_uppercase and q.islower(),
                no_multiply_numbers=True,
            )
        )

        actual_q = self._query_string_from_toklist(toklist)

        # Update the beautified query string, as the actual_q string
        # probably has more correct capitalization
        self.set_beautified_query(actual_q)

        # TODO: We might want to re-tokenize the actual_q string with
        # auto_uppercase=False, since we may have fixed capitalization
        # errors in _query_string_from_toklist()

        if Settings.DEBUG:
            # Log the query string as seen by the parser
            print("Query is: '{0}'".format(actual_q))

        # Fetch banned nonterminals for this query
        for t in self._tree_processors:
            ban_func = getattr(t, "banned_nonterminals", None)
            if ban_func is not None:
                ban_func(self)

        try:
            parse_result, trees = self._parse(toklist)
        except ParseError:
            self.set_error("E_PARSE_ERROR")
            return False

        if not trees:
            # No parse at all
            self.set_error("E_NO_PARSE_TREES")
            return False

        result.update(parse_result)

        if result["num_sent"] != 1:
            # Queries must be one sentence
            self.set_error("E_MULTIPLE_SENTENCES")
            return False
        if result["num_parsed_sent"] != 1:
            # Unable to parse the single sentence
            self.set_error("E_NO_PARSE")
            return False
        if 1 not in trees:
            # No sentence number 1
            self.set_error("E_NO_FIRST_SENTENCE")
            return False
        # Looks good
        # Store the resulting parsed query as a tree
        tree_string = "S1\n" + trees[1]
        if Settings.DEBUG:
            print(tree_string)
        self._tree = QueryTree()
        self._tree.load(tree_string)
        # Store the token list
        self._toklist = toklist
        return True

    def execute_from_plain_text(self) -> bool:
        """Attempt to execute a plain text query, without having to parse it"""
        if not self._query:
            return False
        # Call the handle_plain_text() function in each text processor,
        # until we find one that returns True, or return False otherwise
        return any(
            handle_plain_text(self) for handle_plain_text in self._text_processors
        )

    def execute_from_tree(self) -> bool:
        """Execute the query or queries contained in the previously parsed tree;
        return True if successful"""
        if self._tree is None:
            self.set_error("E_QUERY_NOT_PARSED")
            return False

        # TODO: We should probably try the best tree on all processors
        # before trying the worse trees, instead of all trees per processor,
        # as this sometimes causes issues (e.g. similar parse trees for hue and sonos).
        # TODO: Create generator function which dynamically prioritizes processors

        # Try each tree processor in turn, in priority order (highest priority first)
        for processor in self._tree_processors:
            self._error = None
            self._qtype = None
            # Process the tree, which has only one sentence, but may
            # have multiple matching query nonterminals
            # (children of Query in the grammar)
            try:
                # Note that passing query=self here means that the
                # "query" field of the TreeStateDict is populated,
                # turning it into a QueryStateDict.
                if self._tree.process_queries(
                    self,
                    self._session,
                    processor,
                ):
                    # This processor found an answer, which is already stored
                    # in the Query object: return True
                    return True
            except Exception as e:
                logging.error(
                    f"Exception in execute_from_tree('{processor.get('__name__', 'UNKNOWN')}') "
                    f"for query '{self._query}': {repr(e)}"
                )
        # No processor was able to answer the query
        return False

    def has_answer(self) -> bool:
        """Return True if the query currently has an answer"""
        return bool(self._answer) and self._error is None

    def last_answer(self, *, within_minutes: int = 5) -> Optional[Tuple[str, str]]:
        """Return the last answer given to this client, by default
        within the last 5 minutes (0=forever)"""
        if not self._client_id:
            # Can't find the last answer if no client_id given
            return None
        # Find the newest non-error, no-repeat query result for this client
        q = (
            self._session.query(QueryRow.answer, QueryRow.voice)
            .filter(QueryRow.client_id == self._client_id)
            .filter(QueryRow.qtype != "Repeat")
            .filter(QueryRow.error == None)
        )
        if within_minutes > 0:
            # Apply a timestamp filter
            since = datetime.utcnow() - timedelta(minutes=within_minutes)
            q = q.filter(QueryRow.timestamp >= since)
        # Sort to get the newest query that fulfills the criteria
        last = q.order_by(desc(QueryRow.timestamp)).limit(1).one_or_none()
        return None if last is None else (last[0], last[1])

    def fetch_context(self, *, within_minutes: int = 10) -> Optional[ContextDict]:
        """Return the context from the last answer given to this client,
        by default within the last 10 minutes (0=forever)"""
        if not self._client_id:
            # Can't find the last answer if no client_id given
            return None
        # Find the newest non-error, no-repeat query result for this client
        q = (
            self._session.query(QueryRow.context)
            .filter(QueryRow.client_id == self._client_id)
            .filter(QueryRow.qtype != "Repeat")
            .filter(QueryRow.error == None)
        )
        if within_minutes > 0:
            # Apply a timestamp filter
            since = datetime.utcnow() - timedelta(minutes=within_minutes)
            q = q.filter(QueryRow.timestamp >= since)
        # Sort to get the newest query that fulfills the criteria
        ctx = cast(
            Optional[Sequence[ContextDict]],
            q.order_by(desc(QueryRow.timestamp)).limit(1).one_or_none(),
        )
        # This function normally returns a dict that has been decoded from JSON
        return None if ctx is None else ctx[0]

    @property
    def query(self) -> str:
        """The query text, in its original form"""
        return self._query

    @property
    def query_lower(self) -> str:
        """The query text, all lower case"""
        return self._query.lower()

    @property
    def beautified_query(self) -> str:
        """Return the query string that will be reflected back to the client"""
        return self._beautified_query

    def set_beautified_query(self, q: str) -> None:
        """Set the query string that will be reflected back to the client"""
        self._beautified_query = (
            q.replace("embla", "Embla")
            .replace("miðeind", "Miðeind")
            .replace("Guðni Th ", "Guðni Th. ")  # By presidential request :)
        )

    def lowercase_beautified_query(self) -> None:
        """If we know that no uppercase words occur in the query,
        except the initial capital, this function can be called
        to adjust the beautified query string accordingly."""
        self.set_beautified_query(self._beautified_query.capitalize())

    def query_is_command(self) -> None:
        """Called from a query processor if the query is a command, not a question"""
        # Put a period at the end of the beautified query text
        # instead of a question mark
        if self._beautified_query.endswith("?"):
            self._beautified_query = self._beautified_query[:-1] + "."

    @property
    def expires(self) -> Optional[datetime]:
        """Expiration time stamp for this query answer, if any"""
        return self._expires

    def set_expires(self, ts: datetime) -> None:
        """Set an expiration time stamp for this query answer"""
        self._expires = ts

    @property
    def url(self) -> Optional[str]:
        """URL answer associated with this query"""
        return self._url

    def set_url(self, u: Optional[str]) -> None:
        """Set the URL answer associated with this query"""
        self._url = u

    @property
    def command(self) -> Optional[str]:
        """JavaScript command associated with this query"""
        return self._command

    def set_command(self, c: str) -> None:
        """Set the JavaScript command associated with this query"""
        self._command = c

    @property
    def image(self) -> Optional[str]:
        """Image URL associated with this query"""
        return self._image

    def set_image(self, url: str) -> None:
        """Set the image URL command associated with this query"""
        self._image = url

    @property
    def source(self) -> Optional[str]:
        """Return the source of the answer to this query"""
        return self._source

    def set_source(self, s: str) -> None:
        """Set the source for the answer to this query"""
        self._source = s

    @property
    def location(self) -> Optional[LatLonTuple]:
        """The client location, if known, as a (lat, lon) tuple"""
        return self._location

    @property
    def token_list(self) -> Optional[List[Tok]]:
        """The original token list for the query"""
        return self._toklist

    def qtype(self) -> Optional[str]:
        """Return the query type"""
        return self._qtype

    def ban_nonterminal(self, nonterminal: str) -> None:
        """
        Add a nonterminal to the set of
        banned nonterminals for this query.
        """
        assert nonterminal in self._parser._grammar.nonterminals, (
            f"ban_nonterminal: {nonterminal} doesn't "
            "correspond to a nonterminal in the grammar"
        )
        self._banned_nonterminals.add(nonterminal)

    def ban_nonterminal_set(self, nonterminals: Set[str]) -> None:
        """
        Add a set of nonterminals to the set of
        banned nonterminals for this query.
        """
        diff = nonterminals.difference(self._parser._grammar.nonterminals)
        assert len(diff) == 0, (
            f"ban_nonterminals: nonterminals {diff} don't "
            "correspond to a nonterminal in the grammar"
        )
        self._banned_nonterminals.update(nonterminals)

    def is_nonterminal_banned(self, nt: Nonterminal) -> bool:
        return str(nt) in self._banned_nonterminals

    def set_qtype(self, qtype: str) -> None:
        """Set the query type ('Person', 'Title', 'Company', 'Entity'...)"""
        self._qtype = qtype

    def set_answer(
        self, response: ResponseType, answer: str, voice_answer: Optional[str] = None
    ) -> None:
        """Set the answer to the query"""
        # Detailed response (this is usually a dict)
        self._response = response
        # Single best answer, as a displayable string
        self._answer = answer
        # A voice version of the single best answer
        self._voice_answer = voice_answer

    def set_key(self, key: str) -> None:
        """Set the query key, i.e. the term or string used to execute the query"""
        # This is for instance a person name in nominative case
        self._key = key

    def set_error(self, error: str) -> None:
        """Set an error result"""
        self._error = error

    @property
    def is_voice(self) -> bool:
        """Return True if this is a voice query"""
        return self._voice

    @property
    def client_id(self) -> Optional[str]:
        return self._client_id

    @property
    def client_type(self) -> Optional[str]:
        """Return client type string, e.g. "ios", "android", "www", etc."""
        return self._client_type

    @property
    def client_version(self) -> Optional[str]:
        """Return client version string, e.g. "1.0.3" """
        return self._client_version

    @staticmethod
    def get_dsm(result: Result) -> DSM:
        """Fetch DialogueStateManager instance from result object"""
        dsm = cast(QueryStateDict, result.state)["query"].dsm
        return dsm

    @property
    def dsm(self) -> DSM:
        return self._dsm

    def response(self) -> Optional[ResponseType]:
        """Return the detailed query answer"""
        return self._response

    def answer(self) -> Optional[str]:
        """Return the 'single best' displayable query answer"""
        return self._answer

    def voice_answer(self) -> str:
        """Return a voice version of the 'single best' answer, if any"""
        va = self._voice_answer
        if va is None:
            return ""
        # TODO: Replace acronyms with pronounced characters
        # (ASÍ -> a ess í, BHM -> bé há emm)
        return va

    def key(self) -> Optional[str]:
        """Return the query key"""
        return self._key

    def error(self) -> Optional[str]:
        """Return the query error, if any"""
        return self._error

    @property
    def context(self) -> Optional[ContextDict]:
        """Return the context that has been set by self.set_context()"""
        return self._context

    def set_context(self, ctx: ContextDict) -> None:
        """Set a query context that will be stored and made available
        to the next query from the same client"""
        self._context = ctx

    def client_data(self, key: str) -> Optional[ClientDataDict]:
        """Fetch client_id-associated data stored in the querydata table"""
        if not self.client_id:
            return None
        with SessionContext(read_only=True) as session:
            try:
                client_data = (
                    session.query(QueryData)
                    .filter(QueryData.key == key)
                    .filter(QueryData.client_id == self.client_id)
                ).one_or_none()
                return (
                    None
                    if client_data is None
                    else cast(ClientDataDict, client_data.data)
                )
            except Exception as e:
                logging.error(
                    "Error fetching client '{0}' query data for key '{1}' from db: {2}".format(
                        self.client_id, key, e
                    )
                )
        return None

    @staticmethod
    # TODO: This is a hack to get the query data for a specific device to render connected iot devices
    def get_client_data(client_id: str, key: str) -> Optional[ClientDataDict]:
        """Fetch client_id-associated data stored in the querydata table"""
        with SessionContext(read_only=True) as session:
            try:
                client_data = (
                    session.query(QueryData)
                    .filter(QueryData.key == key)
                    .filter(QueryData.client_id == client_id)
                ).one_or_none()
                return (
                    None
                    if client_data is None
                    else cast(ClientDataDict, client_data.data)
                )
            except Exception as e:
                logging.error(
                    "Error fetching client '{0}' query data for key '{1}' from db: {2}".format(
                        client_id, key, e
                    )
                )
        return None

    def set_client_data(
        self, key: str, data: ClientDataDict, *, update_in_place: bool = False
    ) -> None:
        """Setter for client query data"""
        if not self.client_id or not key:
            logging.warning("Couldn't save query data, no client ID or key")
            return
        Query.store_query_data(
            self.client_id, key, data, update_in_place=update_in_place
        )

    @staticmethod
    def store_query_data(
        client_id: str, key: str, data: ClientDataDict, *, update_in_place: bool = False
    ) -> bool:
        """Save client query data in the database, under the given key"""
        if not client_id or not key:
            return False
        now = datetime.utcnow()
        try:
            with SessionContext(commit=True) as session:
                row = (
                    session.query(QueryData)
                    .filter(QueryData.key == key)
                    .filter(QueryData.client_id == client_id)
                ).one_or_none()
                if row is None:
                    # Not already present: insert
                    row = QueryData(
                        client_id=client_id,
                        key=key,
                        created=now,
                        modified=now,
                        data=data,
                    )
                    session.add(row)
                else:
                    if update_in_place:
                        stored_data = deepcopy(row.data)
                        data = _merge_two_dicts(stored_data, data)
                    # Already present: update
                    row.data = data  # type: ignore
                    row.modified = now  # type: ignore
            # The session is auto-committed upon exit from the context manager
            return True
        except Exception as e:
            logging.error("Error storing query data in db: {0}".format(e))
        return False

    def in_dialogue(self, dialogue_name: str) -> bool:
        return self._dsm.active_dialogue == dialogue_name

    @staticmethod
    def delete_iot_data(client_id: str, iot_group: str, iot_name: str) -> bool:
        """Delete iot data for specific iot_group and iot_name for a client"""
        if not client_id or not iot_group or not iot_name:
            return False
        try:
            with SessionContext(commit=True) as session:
                rows = (
                    session.query(QueryData)
                    .filter(QueryData.client_id == client_id)
                    .filter(QueryData.key == "iot")
                    # .filter(QueryData.data.contains(iot_group))
                    # .filter(QueryData.data.contains(iot_name))
                ).all()
                for row in rows:
                    iot_dict = row.data
                    if iot_group in iot_dict:
                        if iot_name in iot_dict[iot_group]:
                            del iot_dict[iot_group][iot_name]
                            if not iot_dict[iot_group]:
                                del iot_dict[iot_group]
                                if not iot_dict:
                                    session.delete(row)
                    Query.store_query_data(client_id, "iot", iot_dict)
            return True
        except Exception as e:
            logging.error("Error deleting iot data from db: {0}".format(e))
        return False

    @classmethod
    def try_to_help(cls, query: str, result: ResponseDict) -> None:
        """Attempt to help the user in the case of a failed query,
        based on lemmas in the query string"""
        # Collect a set of lemmas that occur in the query string
        lemmas = set()
        with GreynirBin.get_db() as db:
            for token in query.lower().split():
                if token.isalpha():
                    m = db.meanings(token)
                    if not m:
                        # Try an uppercase version, just in case (pun intended)
                        m = db.meanings(token.capitalize())
                    if m:
                        lemmas |= set(mm.stofn.lower().replace("-", "") for mm in m)
        # Collect a list of potential help text functions from the query modules
        help_text_funcs: List[Tuple[str, HelpFunc]] = []
        for lemma in lemmas:
            help_text_funcs.extend(
                [
                    (lemma, help_text_func)
                    for help_text_func in cls._help_texts.get(lemma, [])
                ]
            )
        if help_text_funcs:
            # Found at least one help text func matching a lemma in the query
            # Select a function at random and invoke it with the matched
            # lemma as a parameter
            lemma, help_text_func = random.choice(help_text_funcs)
            result["answer"] = result["voice"] = help_text_func(lemma)
            result["valid"] = True

    def execute(self) -> ResponseDict:
        """Check whether the parse tree is describes a query, and if so,
        execute the query, store the query answer in the result dictionary
        and return True"""
        if Query._parser is None:
            Query.init_class()
        # By default, the result object contains the 'raw' query
        # string (the one returned from the speech-to-text processor)
        # as well as the beautified version of that string - which
        # usually starts with an uppercase letter and has a trailing
        # question mark (or other ending punctuation).
        result: ResponseDict = dict(q_raw=self.query, q=self.beautified_query)
        # First, try to handle this from plain text, without parsing:
        # shortcut to a successful, plain response
        if not self.execute_from_plain_text():
            if not self.parse(result):
                # Unable to parse the query
                err = self.error()
                if err is not None:
                    if Settings.DEBUG:
                        print("Unable to parse query, error {0}".format(err))
                    result["error"] = err
                result["valid"] = False
                return result
            if not self.execute_from_tree():
                # This is a query, but its execution failed for some reason:
                # return the error
                # if Settings.DEBUG:
                #     print("Unable to execute query, error {0}".format(q.error()))
                result["error"] = self.error() or "E_UNABLE_TO_EXECUTE_QUERY"
                result["valid"] = True
                return result
        # Successful query: return the answer in response
        if self._answer:
            result["answer"] = self._answer
        if self._voice:
            # This is a voice query and we have a voice answer to it
            va = self.voice_answer()
            if va:
                result["voice"] = va
        if self._voice:
            # Optimize the response to voice queries:
            # we don't need detailed information about alternative
            # answers or their sources
            result["response"] = dict(answer=self._answer or "")
        elif self._response:
            # Return a detailed response if not a voice query
            result["response"] = self._response
        # Re-assign the beautified query string, in case the query processor modified it
        result["q"] = self.beautified_query
        # ...and the query type, as a string ('Person', 'Entity', 'Title' etc.)
        qt = self.qtype()
        if qt:
            result["qtype"] = qt
        # ...and the key used to retrieve the answer, if any
        key = self.key()
        if key:
            result["key"] = key
        # ...and a URL, if any has been set by the query processor
        if self.url:
            result["open_url"] = self.url
        # ...and a command, if any has been set
        if self.command:
            result["command"] = self.command
        # ...image URL, if any
        if self.image:
            result["image"] = self.image
        # .. and the source, if set by query processor
        if self.source:
            result["source"] = self.source
        key = self.key()
        if not self._voice and qt == "Person" and key is not None:
            # For a person query, add an image (if available)
            img = get_image_url(key, enclosing_session=self._session)
            if img is not None:
                result["image"] = dict(
                    src=img.src,
                    width=img.width,
                    height=img.height,
                    link=img.link,
                    origin=img.origin,
                    name=img.name,
                )
        result["valid"] = True
        if Settings.DEBUG:
            # Dump query results to the console
            def converter(o: object):
                """Ensure that datetime is output in ISO format to JSON"""
                if isinstance(o, datetime):
                    return o.isoformat()[0:16]
                return None

            print(
                json.dumps(
                    {
                        k: (f"{v[:100]} ... {v[-100:]}")
                        if isinstance(v, str) and len(v) > 1000
                        else v
                        for k, v in result.items()
                        # This ^ is just to shorten very long lines
                    },
                    indent=3,
                    ensure_ascii=False,
                    default=converter,
                )
            )
        return result


def _to_case(
    np: str,
    lookup_func: LookupFunc,
    cast_func: CastFunc,
    filter_func: Optional[BinFilterFunc],
) -> str:
    """Return the noun phrase after casting it from nominative to accusative case"""
    # Split the phrase into words and punctuation, respectively
    a = re.split(r"([\w]+)", np)
    seen_preposition = False
    # Enumerate through the 'tokens'
    for ix, w in enumerate(a):
        if not w:
            continue
        if w == "- ":
            # Something like 'Skeiða- og Hrunamannavegur'
            continue
        if w.strip() in {"-", "/"}:
            # Reset the seen_preposition flag after seeing a hyphen or slash
            seen_preposition = False
            continue
        if seen_preposition:
            continue
        if re.match(r"^[\w]+$", w):
            # This is a word: begin by looking up the word form
            _, mm = lookup_func(w)
            if not mm:
                # Unknown word form: leave it as-is
                continue
            if any(m.ordfl == "fs" for m in mm):
                # Probably a preposition: don't modify it, but
                # stop casting until the end of this phrase
                seen_preposition = True
                continue
            # Cast the word to the case we want
            a[ix] = cast_func(w, filter_func=filter_func)
    # Reassemble the list of words and punctuation
    return "".join(a)


def to_accusative(np: str, *, filter_func: Optional[BinFilterFunc] = None) -> str:
    """Return the noun phrase after casting it from nominative to accusative case"""
    with GreynirBin.get_db() as db:
        return _to_case(
            np,
            db.lookup_g,
            db.cast_to_accusative,
            filter_func=filter_func,
        )


def to_dative(np: str, *, filter_func: Optional[BinFilterFunc] = None) -> str:
    """Return the noun phrase after casting it from nominative to dative case"""
    with GreynirBin.get_db() as db:
        return _to_case(
            np,
            db.lookup_g,
            db.cast_to_dative,
            filter_func=filter_func,
        )


def to_genitive(np: str, *, filter_func: Optional[BinFilterFunc] = None) -> str:
    """Return the noun phrase after casting it from nominative to genitive case"""
    with GreynirBin.get_db() as db:
        return _to_case(
            np,
            db.lookup_g,
            db.cast_to_genitive,
            filter_func=filter_func,
        )


def process_query(
    q: Union[str, Iterable[str]],
    voice: bool,
    *,
    auto_uppercase: bool = False,
    location: Optional[LatLonTuple] = None,
    remote_addr: Optional[str] = None,
    client_id: Optional[str] = None,
    client_type: Optional[str] = None,
    client_version: Optional[str] = None,
    bypass_cache: bool = False,
    private: bool = False,
) -> ResponseDict:

    """Process an incoming natural language query.
    If voice is True, return a voice-friendly string to
    be spoken to the user. If auto_uppercase is True,
    the string probably came from voice input and we
    need to intelligently guess which words in the query
    should be upper case (to the extent that it matters).
    The q parameter can either be a single query string
    or an iterable of strings that will be processed in
    order until a successful one is found."""

    now = datetime.utcnow()
    result: ResponseDict = dict()
    client_id = client_id[:256] if client_id else None
    first_clean_q: Optional[str] = None
    first_qtext = ""

    with SessionContext(commit=True) as session:

        it: Iterable[str]
        if isinstance(q, str):
            # This is a single string
            it = [q]
        else:
            # This should be an array of strings,
            # in decreasing priority order
            it = q

        # Iterate through the submitted query strings,
        # assuming that they are in decreasing order of probability,
        # attempting to execute them in turn until we find
        # one that works (or we're stumped)
        for qtext in it:

            qtext = qtext.strip()
            clean_q = qtext.rstrip("?")
            if first_clean_q is None:
                # Store the first (most likely) query string
                # that comes in from the speech-to-text processor,
                # since we want to return that one to the client
                # if no query string is matched - not the last
                # (least likely) query string
                first_clean_q = clean_q
                first_qtext = qtext

            # First, look in the query cache for the same question
            # (in lower case), having a not-expired answer
            cached_answer = None
            if voice and not bypass_cache:
                # Only use the cache for voice queries
                # (handling detailed responses in other queries
                # is too much for the cache)
                cached_answer = (
                    session.query(QueryRow)
                    .filter(QueryRow.question_lc == clean_q.lower())
                    .filter(QueryRow.expires >= now)
                    .order_by(desc(QueryRow.expires))
                    .limit(1)
                    .one_or_none()
                )
            if cached_answer is not None:
                # The same question is found in the cache and has not expired:
                # return the previous answer
                a = cached_answer
                result = dict(
                    valid=True,
                    q_raw=qtext,
                    q=a.bquestion,
                    answer=a.answer,
                    response=dict(answer=a.answer or ""),
                    voice=a.voice,
                    expires=a.expires,
                    qtype=a.qtype,
                    key=a.key,
                )
                # !!! TBD: Log the cached answer as well?
                return result

            # The answer is not found in the cache: Handle the query
            query = Query(
                session,
                qtext,
                voice,
                auto_uppercase,
                location,
                client_id,
                client_type,
                client_version,
            )
            result = query.execute()
            if result["valid"] and "error" not in result:
                # Successful: our job is done
                if not private:
                    # If not in private mode, log the result
                    try:
                        # Standard query logging
                        qrow = QueryRow(
                            timestamp=now,
                            interpretations=it,
                            question=clean_q,
                            # bquestion is the beautified query string
                            bquestion=result["q"],
                            answer=result["answer"],
                            voice=result.get("voice"),
                            # Only put an expiration on voice queries
                            expires=query.expires if voice else None,
                            qtype=result.get("qtype"),
                            key=result.get("key"),
                            latitude=None,
                            longitude=None,
                            # Client identifier
                            client_id=client_id[:256] if client_id else None,
                            client_type=client_type[:80] if client_type else None,
                            client_version=client_version[:10]
                            if client_version
                            else None,
                            # IP address
                            remote_addr=remote_addr or None,
                            # Context dict, stored as JSON, if present
                            # (set during query execution)
                            context=query.context,
                            # All other fields are set to NULL
                        )
                        session.add(qrow)
                        # Also log anonymised query
                        session.add(QueryLog.from_Query(qrow))
                    except Exception as e:
                        logging.error("Error logging query: {0}".format(e))
                return result

        # Failed to answer the query, i.e. no query processor
        # module was able to parse the query and provide an answer
        result = result or dict(valid=False, error="E_NO_RESULT")
        if first_clean_q:
            # Re-insert the query data from the first (most likely)
            # string returned from the speech-to-text processor,
            # replacing residual data that otherwise would be there
            # from the last (least likely) query string
            result["q_raw"] = first_qtext
            result["q"] = beautify_query(first_qtext)
            # Attempt to include a helpful response in the result
            Query.try_to_help(first_clean_q, result)

            # Log the failure
            qrow = QueryRow(
                timestamp=now,
                interpretations=it,
                question=first_clean_q,
                bquestion=result["q"],
                answer=result.get("answer"),
                voice=result.get("voice"),
                error=result.get("error"),
                latitude=location[0] if location else None,
                longitude=location[1] if location else None,
                # Client identifier
                client_id=client_id,
                client_type=client_type or None,
                client_version=client_version or None,
                # IP address
                remote_addr=remote_addr or None
                # All other fields are set to NULL
            )
            session.add(qrow)
            # Also log anonymised query
            session.add(QueryLog.from_Query(qrow))

    return result
