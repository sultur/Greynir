"""

    Greynir: Natural language processing for Icelandic

    Repeat-after-me query response module

    Copyright (C) 2020 Miðeind ehf.

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


    This module handles queries where the user requests that a certain
    text segment be repeated back to him/her.

"""

from queries import gen_answer
from datetime import datetime, timedelta

_REPEAT_QTYPE = "Repeat"


_REPEAT_PREFIXES = tuple(
    (
        "segðu orðið",
        "segðu orðin",
        "segðu setninguna",
        "segðu eftirfarandi",
        "endurtaktu eftirfarandi",
        "endurtaktu setninguna",
        "endurtaktu eftir mér",
        "endurtaktu orðið",
        "endurtaktu orðin",
        "endurtaktu",
        # "segðu",
    )
)

# _PREFIX_BLACKLIST = frozenset(
#     ("segðu mér", "segðu okkur", "segðu eitthvað", "segðu frá")
# )


def gen_repeat_answ(text, cmd_prefix, q):
    atxt = text.strip()
    atxt = text[:1].upper() + text[1:]  # Capitalize first character
    q.set_answer(*gen_answer(atxt))
    q.set_qtype(_REPEAT_QTYPE)
    q.set_key("Repeat")
    q.set_expires(datetime.utcnow() + timedelta(hours=24))

    # Beautify query by placing text to repeat within quotation marks
    q.set_beautified_query("{0}„{1}.“".format(cmd_prefix.capitalize(), atxt))


def handle_plain_text(q):
    """ Handles a plain text query. """
    ql = q.query_lower.rstrip("?")

    # for blw in _PREFIX_BLACKLIST:
    #     if ql.startswith(blw):
    #         return False

    qlen = len(ql)

    for r in _REPEAT_PREFIXES:
        pfx = r + " "
        plen = len(pfx)
        if ql.startswith(pfx) and qlen > plen:
            rtxt = q.query[plen:]
            gen_repeat_answ(rtxt, pfx, q)
            return True

    return False
