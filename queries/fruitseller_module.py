from typing import Any, List, Optional, cast
import json
import logging
import datetime

from query import Query, QueryStateDict
from tree import Result, Node, TerminalNode
from reynir import NounPhrase
from queries import gen_answer, AnswerTuple, parse_num, natlang_seq, sing_or_plur
from queries.dialogue import (
    AnsweringFunctionMap,
    DialogueStateManager,
)
from queries.resources import (
    DateResource,
    ListResource,
    Resource,
    ResourceState,
    TimeResource,
    FinalResource,
    WrapperResource,
)

# Indicate that this module wants to handle parse trees for queries,
# as opposed to simple literal text strings
HANDLE_TREE = True
DIALOGUE_NAME = "fruitseller"

# The grammar nonterminals this module wants to handle
QUERY_NONTERMINALS = {"QFruitSeller"}

# The context-free grammar for the queries recognized by this plug-in module
GRAMMAR = """

Query →
    QFruitSeller '?'?

QFruitSeller →
    QFruitStartQuery
    | QFruitQuery
    | QFruitDateQuery
    | QFruitInfoQuery

QFruitInfoQuery →
    "hver"? "er"? "staðan" "á"? "ávaxtapöntuninni"?

QFruitStartQuery →
    "ávöxtur" | "postur" | "póstur"
    | "ég" "vill" "kaupa"? "ávexti"
    | "ég" "vil" "kaupa"? "ávexti"
    | "mig" "langar" "að" "kaupa" "ávexti" "hjá"? "þér"?
    | "mig" "langar" "að" "panta" "ávexti" "hjá"? "þér"?
    | "get" "ég" "keypt" "ávexti" "hjá" "þér"

QFruitQuery →
    QAddFruitQuery
    | QRemoveFruitQuery
    | QChangeFruitQuery
    | QFruitOptionsQuery
    | QYes
    | QNo
    | QCancelOrder

QAddFruitQuery →
    "já"? "má"? "ég"? "fá"? QFruitList
    | "já"? "get" "ég" "fengið" QFruitList
    | "já"? "gæti" "ég" "fengið" QFruitList
    | "já"? "ég" "vil" "fá" QFruitList
    | "já"? "ég" "vill" "fá" QFruitList
    | "já"? "ég" "vil" "panta" QFruitList
    | "já"? "ég" "vill" "panta" QFruitList
    | "já"? "ég" "vil" "kaupa" QFruitList
    | "já"? "ég" "vill" "kaupa" QFruitList
    | "já"? "mig" "langar" "að" "fá" QFruitList
    | "já"? "mig" "langar" "að" "kaupa" QFruitList
    | "já"? "mig" "langar" "að" "panta" QFruitList

QRemoveFruitQuery →
    "taktu" "út" QFruitList
    | "slepptu" QFruitList
    | "ég"? "vil"? "sleppa" QFruitList
    | "ég" "vill" "sleppa" QFruitList
    | "ég" "hætti" "við" QFruitList
    | "ég" "vil" "ekki" QFruitList
    | "ég" "vill" "ekki" QFruitList

QChangeFruitQuery →
    QChangeStart QFruitList QChangeConnector QFruitList

QChangeStart →
    "breyttu"
    | "ég" "vil" "frekar"
    | "ég" "vill" "frekar"
    | "ég" "vil" "skipta" "út"
    | "ég" "vill" "skipta" "út"
    | "ég" "vil" "breyta"
    | "ég" "vill" "breyta"

QChangeConnector →
    "en" | "í" "staðinn" "fyrir"

QFruitOptionsQuery →
    "hvað" "er" "í" "boði"
    | "hverjir" "eru" "valmöguleikarnir"
    | "hvaða" "valmöguleikar" "eru" "í" "boði"
    | "hvaða" "valmöguleikar" "eru" "til"
    | "hvaða" "ávexti" "ertu" "með"
    | "hvaða" "ávextir" "eru" "í" "boði"

QFruitList → QNumOfFruit QNumOfFruit*

QNumOfFruit → QNum? QFruit "og"?

QNum →
    # to is a declinable number word ('tveir/tvo/tveim/tveggja')
    # töl is an undeclinable number word ('sautján')
    # tala is a number ('17')
    to | töl | tala

QFruit → 'banani' | 'epli' | 'pera' | 'appelsína'

QYes → "já" "já"* | "endilega" | "já" "takk" | "játakk" | "já" "þakka" "þér" "fyrir" | "já" "takk" "kærlega" "fyrir"? | "jább" "takk"?

QNo → "nei" "takk"? | "nei" "nei"* | "neitakk" | "ómögulega"

QCancelOrder → "ég" "hætti" "við"
    | "ég" "vil" "hætta" "við" "pöntunina"?
    | "ég" "vill" "hætta" "við" "pöntunina"

QFruitDateQuery →
    QFruitDateTime
    | QFruitDate
    | QFruitTime

QFruitDateTime →
    tímapunkturafs

QFruitDate →
    dagsafs
    | dagsföst

QFruitTime →
    "klukkan"? tími

"""

_START_DIALOGUE_QTYPE = "QFruitStartQuery"
_DIALOGUE_NAME = "fruitseller"


def _generate_fruit_answer(
    resource: ListResource, dsm: DialogueStateManager, result: Result
) -> Optional[AnswerTuple]:
    if result.get("fruitsEmpty"):
        return gen_answer(resource.prompts["empty"])
    if result.get("fruitOptions"):
        return gen_answer(resource.prompts["options"])
    if resource.is_unfulfilled:
        return gen_answer(resource.prompts["initial"])
    if resource.is_partially_fulfilled:
        ans: str = ""
        if "actually_removed_something" in result:
            if not result["actually_removed_something"]:
                ans += "Ég fann ekki ávöxtinn sem þú vildir fjarlægja. "
        return gen_answer(
            ans
            + resource.prompts["repeat"].format(list_items=_list_items(resource.data))
        )
    if resource.is_fulfilled:
        return gen_answer(
            resource.prompts["confirm"].format(list_items=_list_items(resource.data))
        )
    return None


def _generate_datetime_answer(
    resource: Resource, dsm: DialogueStateManager, result: Result
) -> Optional[AnswerTuple]:
    ans: Optional[str] = None
    date_resource: DateResource = cast(DateResource, dsm.get_resource("Date"))
    time_resource: TimeResource = cast(TimeResource, dsm.get_resource("Time"))

    if resource.is_unfulfilled:
        ans = resource.prompts["initial"]
    elif resource.is_partially_fulfilled:
        if date_resource.is_fulfilled:
            ans = resource.prompts["date_fulfilled"].format(
                date=date_resource.data.strftime("%Y/%m/%d")
            )
        elif time_resource.is_fulfilled:
            ans = resource.prompts["time_fulfilled"].format(
                time=time_resource.data.strftime("%H:%M")
            )
    elif resource.is_fulfilled:
        ans = resource.prompts["confirm"].format(
            date_time=datetime.datetime.combine(
                date_resource.data,
                time_resource.data,
            ).strftime("%Y/%m/%d %H:%M")
        )
    if ans:
        return gen_answer(ans)
    return None


def _generate_final_answer(
    resource: FinalResource, dsm: DialogueStateManager, result: Result
) -> Optional[AnswerTuple]:
    ans: Optional[str] = None
    if resource.is_cancelled:
        return gen_answer(resource.prompts["cancelled"])

    dsm.set_resource_state(resource.name, ResourceState.CONFIRMED)
    date_resource = dsm.get_resource("Date")
    time_resource = dsm.get_resource("Time")
    ans = resource.prompts["final"].format(
        fruits=_list_items(dsm.get_resource("Fruits").data),
        date_time=datetime.datetime.combine(
            date_resource.data,
            time_resource.data,
        ).strftime("%Y/%m/%d %H:%M"),
    )
    return gen_answer(ans)


def _list_items(items: Any) -> str:
    item_list: List[str] = []
    for num, name in items:
        # TODO: get general plural form
        plural_name: str = NounPhrase(name).dative or name
        item_list.append(sing_or_plur(num, name, plural_name))
    return natlang_seq(item_list)


def QFruitStartQuery(node: Node, params: QueryStateDict, result: Result):
    result.qtype = _START_DIALOGUE_QTYPE


def QAddFruitQuery(node: Node, params: QueryStateDict, result: Result):
    result.qtype = "QAddFruitQuery"
    dsm: DialogueStateManager = cast(QueryStateDict, result.state)["query"].dsm
    resource: ListResource = cast(ListResource, dsm.get_resource("Fruits"))
    if resource.data is None:
        resource.data = []
    query_fruit_index = 0
    while query_fruit_index < len(result.queryfruits):
        (number, name) = result.queryfruits[query_fruit_index]
        added = False
        for index, (fruit_number, fruit_name) in enumerate(resource.data):
            if fruit_name == name:
                resource.data[index] = (number + fruit_number, name)
                added = True
                break
        if not added:
            resource.data.append((number, name))
        query_fruit_index += 1
    dsm.set_resource_state(resource.name, ResourceState.PARTIALLY_FULFILLED)


def QRemoveFruitQuery(node: Node, params: QueryStateDict, result: Result):
    result.qtype = "QRemoveFruitQuery"
    dsm: DialogueStateManager = cast(QueryStateDict, result.state)["query"].dsm
    resource: ListResource = cast(ListResource, dsm.get_resource("Fruits"))
    result.actually_removed_something = False
    if resource.data is not None:
        for _, fruitname in result.queryfruits:
            for number, name in resource.data:
                if name == fruitname:
                    resource.data.remove([number, name])
                    result.actually_removed_something = True
                    break
    if len(resource.data) == 0:
        dsm.set_resource_state(resource.name, ResourceState.UNFULFILLED)
        result.fruitsEmpty = True
    else:
        dsm.set_resource_state(resource.name, ResourceState.PARTIALLY_FULFILLED)


def QCancelOrder(node: Node, params: QueryStateDict, result: Result):
    dsm: DialogueStateManager = cast(QueryStateDict, result.state)["query"].dsm
    dsm.set_resource_state("Final", ResourceState.CANCELLED)
    dsm.end_dialogue()


def QFruitOptionsQuery(node: Node, params: QueryStateDict, result: Result):
    result.qtype = "QFruitOptionsQuery"
    result.answer_key = ("Fruits", "options")
    result.fruitOptions = True


def QYes(node: Node, params: QueryStateDict, result: Result):

    result.qtype = "QYes"
    dsm: DialogueStateManager = cast(QueryStateDict, result.state)["query"].dsm
    resource = dsm.current_resource
    if (
        not resource.is_confirmed and resource.name in ("Fruits", "DateTime")
    ) and resource.is_fulfilled:
        dsm.set_resource_state(resource.name, ResourceState.CONFIRMED)
        if isinstance(resource, WrapperResource):
            for rname in resource.requires:
                dsm.get_resource(rname).state = ResourceState.CONFIRMED


def QNo(node: Node, params: QueryStateDict, result: Result):
    result.qtype = "QNo"
    dsm: DialogueStateManager = cast(QueryStateDict, result.state)["query"].dsm
    resource = dsm.current_resource
    if resource.name == "Fruits" and not resource.is_confirmed:
        if resource.is_partially_fulfilled:
            resource.state = ResourceState.FULFILLED
        elif resource.is_fulfilled:
            resource.state = ResourceState.PARTIALLY_FULFILLED


def QNumOfFruit(node: Node, params: QueryStateDict, result: Result):
    if "queryfruits" not in result:
        result["queryfruits"] = []
    if "fruitnumber" not in result:
        result.queryfruits.append([1, result.fruit])
    else:
        result.queryfruits.append([result.fruitnumber, result.fruit])


def QNum(node: Node, params: QueryStateDict, result: Result):
    fruitnumber = int(parse_num(node, result._nominative))
    if fruitnumber is not None:
        result.fruitnumber = fruitnumber
    else:
        result.fruitnumber = 1


def QFruit(node: Node, params: QueryStateDict, result: Result):
    fruit = result._root
    if fruit is not None:
        result.fruit = fruit


def _add_date(
    resource: DateResource, dsm: DialogueStateManager, result: Result
) -> None:
    if dsm.get_resource("Fruits").is_confirmed:
        resource.set_date(result["delivery_date"])
        resource.state = ResourceState.FULFILLED
        time_resource = dsm.get_resource("Time")
        datetime_resource = dsm.get_resource("DateTime")
        if time_resource.is_fulfilled:
            datetime_resource.state = ResourceState.FULFILLED
        else:
            datetime_resource.state = ResourceState.PARTIALLY_FULFILLED


def QFruitDate(node: Node, params: QueryStateDict, result: Result) -> None:
    result.qtype = "bull"
    datenode = node.first_child(lambda n: True)
    assert isinstance(datenode, TerminalNode)
    cdate = datenode.contained_date
    if cdate:
        y, m, d = cdate
        now = datetime.datetime.utcnow()

        # This is a date that contains at least month & mday
        if d and m:
            if not y:
                y = now.year
                # Bump year if month/day in the past
                if m < now.month or (m == now.month and d < now.day):
                    y += 1
            result["delivery_date"] = datetime.date(day=d, month=m, year=y)
            dsm: DialogueStateManager = cast(QueryStateDict, result.state)["query"].dsm
            if dsm.current_resource.name == "DateTime":
                _add_date(cast(DateResource, dsm.get_resource("Date")), dsm, result)
            return
    raise ValueError("No date in {0}".format(str(datenode)))


def _add_time(
    resource: TimeResource, dsm: DialogueStateManager, result: Result
) -> None:
    if dsm.get_resource("Fruits").is_confirmed:
        resource.set_time(result["delivery_time"])
        resource.state = ResourceState.FULFILLED
        date_resource = dsm.get_resource("Date")
        datetime_resource = dsm.get_resource("DateTime")
        if date_resource.is_fulfilled:
            datetime_resource.state = ResourceState.FULFILLED
        else:
            datetime_resource.state = ResourceState.PARTIALLY_FULFILLED


def QFruitTime(node: Node, params: QueryStateDict, result: Result):
    result.qtype = "bull"
    # Extract time from time terminal nodes
    tnode = cast(TerminalNode, node.first_child(lambda n: n.has_t_base("tími")))
    if tnode:
        aux_str = tnode.aux.strip("[]")
        hour, minute, _ = (int(i) for i in aux_str.split(", "))
        if hour in range(0, 24) and minute in range(0, 60):
            result["delivery_time"] = datetime.time(hour, minute)
            dsm: DialogueStateManager = cast(QueryStateDict, result.state)["query"].dsm
            if dsm.current_resource.name == "DateTime":
                _add_time(cast(TimeResource, dsm.get_resource("Time")), dsm, result)
        else:
            result["parse_error"] = True


def QFruitDateTime(node: Node, params: QueryStateDict, result: Result) -> None:
    result.qtype = "bull"
    datetimenode = node.first_child(lambda n: True)
    assert isinstance(datetimenode, TerminalNode)
    now = datetime.datetime.now()
    y, m, d, h, min, _ = (i if i != 0 else None for i in json.loads(datetimenode.aux))
    if y is None:
        y = now.year
    dsm: DialogueStateManager = cast(QueryStateDict, result.state)["query"].dsm
    if d is not None and m is not None:
        result["delivery_date"] = datetime.date(y, m, d)
        if result["delivery_date"] < now.date():
            result["delivery_date"].year += 1
        if dsm.current_resource.name == "DateTime":
            _add_date(cast(DateResource, dsm.get_resource("Date")), dsm, result)

    if h is not None and min is not None:
        result["delivery_time"] = datetime.time(h, min)
        if dsm.current_resource.name == "DateTime":
            _add_time(cast(TimeResource, dsm.get_resource("Time")), dsm, result)


def QFruitInfoQuery(node: Node, params: QueryStateDict, result: Result):
    result.qtype = "QFruitInfo"


_ANSWERING_FUNCTIONS: AnsweringFunctionMap = {
    "Fruits": _generate_fruit_answer,
    "DateTime": _generate_datetime_answer,
    "Final": _generate_final_answer,
}


def sentence(state: QueryStateDict, result: Result) -> None:
    """Called when sentence processing is complete"""
    q: Query = state["query"]
    dsm: DialogueStateManager = q.dsm

    if dsm.not_in_dialogue():
        q.set_error("E_QUERY_NOT_UNDERSTOOD")
        return

    # Successfully matched a query type
    try:
        # if result.qtype == "QFruitInfo":
        #     # Example info handling functionality
        #     # ans = "Ávaxtapöntunin þín er bara flott. "
        #     # f = dsm.get_resource("Fruits")
        #     # ans += str(f.data)
        #     ans = dsm.get_answer()
        #     if not ans:
        #         print("No answer generated")
        #         q.set_error("E_QUERY_NOT_UNDERSTOOD")
        #         return

        #     q.set_answer(*ans)
        #     return

        ans = dsm.get_answer(_ANSWERING_FUNCTIONS, result)
        if not ans:
            print("No answer generated")
            q.set_error("E_QUERY_NOT_UNDERSTOOD")
            return

        q.set_qtype(result.qtype)
        q.set_answer(*ans)
        return
    except Exception as e:
        logging.warning(
            "Exception {0} while processing fruit seller query '{1}'".format(e, q.query)
        )
        q.set_error("E_EXCEPTION: {0}".format(e))
