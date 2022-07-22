from typing import (
    Any,
    Callable,
    Dict,
    Mapping,
    Set,
    List,
    Optional,
    TypeVar,
    cast,
)
from typing_extensions import TypedDict, NotRequired

import os.path
import json
import datetime

try:
    import tomllib  # type: ignore (module not available in Python <3.11)
except ModuleNotFoundError:
    import tomli as tomllib  # Used for Python <3.11

from queries import AnswerTuple
from queries.resources import (
    RESOURCE_MAP,
    OrResource,
    Resource,
    DialogueJSONDecoder,
    DialogueJSONEncoder,
    ResourceState,
    WrapperResource,
)

# TODO:? Delegate answering from a resource to another resource or to another dialogue
# TODO:? í ávaxtasamtali "ég vil panta flug" "viltu að ég geymi ávaxtapöntunina eða eyði henni?" ...
# TODO: Add timezone info to json encoding/decoding?
# TODO: FIX TYPE HINTS (esp. 'Any')
# TODO: Add specific prompt handling to DSM to remove result from DSM.
# TODO: Add try-except blocks where appropriate

_TOML_FOLDER_NAME = "dialogues"
_DEFAULT_EXPIRATION_TIME = 30 * 60  # a dialogue expires after 30 minutes
_FINAL_RESOURCE_NAME = "Final"

# Generic resource type
ResourceType_co = TypeVar("ResourceType_co", bound="Resource")

# Types for use in generating prompts/answers
AnsweringFunctionType = Callable[
    [ResourceType_co, "DialogueStateManager", Any], Optional[AnswerTuple]
]
# TODO: Fix 'Any' in type hint (Callable args are contravariant)
AnsweringFunctionMap = Mapping[str, AnsweringFunctionType[Any]]

FilterFuncType = Callable[[Resource, int], bool]
_ALLOW_ALL_FILTER: FilterFuncType = lambda r, i: True

################################
#    DIALOGUE STATE MANAGER    #
################################


class ResourceNotFoundError(Exception):
    ...


class ResourceGraphItem(TypedDict):
    """Type for a node in the resource graph."""

    children: List[Resource]
    parents: List[Resource]


# Dependency relationship graph type for resources
ResourceGraph = Dict[Resource, ResourceGraphItem]


class DialogueTOMLStructure(TypedDict):
    """Structure of a dialogue TOML file."""

    resources: List[Dict[str, Any]]
    dynamic_resources: List[Dict[str, Any]]
    expiration_time: NotRequired[int]


# Keys for accessing saved client data for dialogues
# (must match typed dict attributes below)
_RESOURCES_KEY = "resources"
_DYNAMIC_RESOURCES_KEY = "dynamic_resources"
_MODIFIED_KEY = "modified"
_EXTRAS_KEY = "extras"
_EXPIRATION_TIME_KEY = "expiration_time"


# Dialogue data
DialogueDataDict = Dict[str, str]


class DialogueDBStructure(TypedDict):
    """
    Representation of the dialogue structure,
    as it is saved to the database.
    """

    resources: Dict[str, Resource]
    modified: datetime.datetime
    extras: Dict[str, Any]


class DialogueStateManager:
    DIALOGUE_DATA_KEY = "dialogue"

    def __init__(self, dialogue_data: DialogueDataDict) -> None:
        self._dialogue_data: DialogueDataDict = dialogue_data

    def load_dialogue(self, dialogue_name: str):
        self._dialogue_name: str = dialogue_name
        # Dict mapping resource name to resource instance
        self._resources: Dict[str, Resource] = {}
        # Boolean indicating if the client is in this dialogue
        self._in_this_dialogue: bool = False
        # Extra information saved with the dialogue state
        self._extras: Dict[str, Any] = {}
        # Answer for the current query
        self._answer_tuple: Optional[AnswerTuple] = None
        # Latest non-confirmed resource
        self._current_resource: Optional[Resource] = None
        # Dependency graph for the resources
        self._resource_graph: ResourceGraph = {}
        # Database data for this dialogue, if any
        self._saved_state: Optional[DialogueDBStructure] = None
        # Whether this dialogue is finished (successful/cancelled) or not
        self._finished: bool = False
        self._expiration_time: int = _DEFAULT_EXPIRATION_TIME
        self._timed_out: bool = False
        self._initial_resource = None

        dialogue_saved_state: Optional[str] = self._dialogue_data.get(
            dialogue_name, None
        )
        if isinstance(dialogue_saved_state, str):
            self._saved_state = cast(
                DialogueDBStructure,
                json.loads(dialogue_saved_state, cls=DialogueJSONDecoder),
            )

            # Check that we have saved data for this dialogue and that it is not expired
            if self._saved_state[_RESOURCES_KEY]:
                self._in_this_dialogue = True
                self.setup_resources()
        else:
            print("NO DIALOGUE DATA FOR", dialogue_name)

    def setup_resources(self) -> None:
        """
        Load dialogue resources from TOML file and update their state from database data.
        """
        print("Setting up resources")
        # TODO: Only initialize if not hotword activated
        # Fetch empty resources from TOML
        self._initialize_resources(self._dialogue_name)
        if self._saved_state:
            time_from_last_interaction = (
                datetime.datetime.now() - self._saved_state[_MODIFIED_KEY]
            )
            # The dialogue timed out, nothing should be done
            if time_from_last_interaction.total_seconds() >= self._expiration_time:
                self._timed_out = True
                return
        # Update empty resources with data from database
        for rname, resource in self._resources.items():
            if self._saved_state and rname in self._saved_state["resources"]:
                resource.update(self._saved_state[_RESOURCES_KEY][rname])
            # Change from int to enum type
            resource.state = ResourceState(resource.state)
        # Set extra data from database
        if self._saved_state and _EXTRAS_KEY in self._saved_state:
            self._extras = self._saved_state.get(_EXTRAS_KEY) or self._extras
        # Create resource dependency relationship graph
        print("Initializing resource graph")
        self._initialize_resource_graph()
        print("Finished setting up resources")

    def _initialize_resource_graph(self) -> None:
        """
        Initializes the resource graph with each
        resource having children and parents according
        to what each resource requires.
        """
        for resource in self._resources.values():
            print("Initializing resource graph for", resource.name)
            if resource.order_index == 0 and self._initial_resource is None:
                self._initial_resource = resource
            self._resource_graph[resource] = {"children": [], "parents": []}
        print("Children/parents set up, starting to fill:")
        for resource in self._resources.values():
            print("In outer for loop")
            for req in resource.requires:
                print("Appending parents and children for resource", req)
                self._resource_graph[self._resources[req]]["parents"].append(resource)
                self._resource_graph[resource]["children"].append(self._resources[req])
                print("Done appending parents and children for resource", req)
        print("Resource graph: ", self._resource_graph)

    def _initialize_resources(self, filename: str) -> None:
        """
        Loads dialogue structure from TOML file and
        fills self._resources with empty Resource instances.
        """
        if self._saved_state:
            print("IN IFFFFFF with resources: ", self._saved_state[_RESOURCES_KEY])
            self._resources = {}
            for rname, resource in self._saved_state[_RESOURCES_KEY].items():
                print("Adding resource", rname)
                self._resources[rname] = resource
            self._expiration_time = self._saved_state.get(
                "expiration_time", _DEFAULT_EXPIRATION_TIME
            )
        else:
            basepath, _ = os.path.split(os.path.realpath(__file__))
            fpath = os.path.join(basepath, _TOML_FOLDER_NAME, filename + ".toml")
            with open(fpath, mode="r") as file:
                f = file.read()
            # Read TOML file containing a list of resources for the dialogue
            obj: DialogueTOMLStructure = tomllib.loads(f)  # type: ignore
            assert _RESOURCES_KEY in obj, f"No resources found in TOML file {f}"
            # Create resource instances from TOML data and return as a dict
            for i, resource in enumerate(obj[_RESOURCES_KEY]):
                assert "name" in resource, f"Name missing for resource {i+1}"
                if "type" not in resource:
                    resource["type"] = "Resource"
                # Create instances of Resource classes (and its subclasses)
                self._resources[resource["name"]] = RESOURCE_MAP[resource["type"]](
                    **resource, order_index=i
                )
            self._expiration_time = obj.get("expiration_time", _DEFAULT_EXPIRATION_TIME)

    def add_dynamic_resource(self, resource_name: str, parent_name: str) -> None:
        """
        Adds a dynamic resource to the dialogue from TOML file and
        updates the requirements of it's parents.
        """
        # TODO: should dynamic resources be loaded from TOML at initialization?
        # Loading dynamic resources from TOML
        basepath, _ = os.path.split(os.path.realpath(__file__))
        fpath = os.path.join(basepath, _TOML_FOLDER_NAME, self._dialogue_name + ".toml")
        with open(fpath, mode="r") as file:
            f = file.read()

        obj: DialogueTOMLStructure = tomllib.loads(f)  # type: ignore
        assert (
            _DYNAMIC_RESOURCES_KEY in obj
        ), f"No dynamic resources found in TOML file {f}"
        parent_resource: Resource = self.get_resource(parent_name)
        order_index: int = parent_resource.order_index
        dynamic_resources: Dict[str, Resource] = {}
        # Index of dynamic resource
        dynamic_resource_index = (
            len(
                [
                    i
                    for i in self._resources
                    if self.get_resource(i).name.startswith(resource_name + "_")
                ]
            )
            + 1
        )
        # TODO: Only update index for added dynamic resources (don't loop through all, just the added ones)
        # Adding all dynamic resources to a list
        for dynamic_resource in obj[_DYNAMIC_RESOURCES_KEY]:
            assert "name" in dynamic_resource, f"Name missing for dynamic resource"
            if "type" not in dynamic_resource:
                dynamic_resource["type"] = "Resource"
            # Updating required resources to have indexed name
            dynamic_resource["requires"] = [
                f"{res}_{dynamic_resource_index}"
                for res in dynamic_resource.get("requires", [])
            ]
            # Updating dynamic resource name to have indexed name
            dynamic_resource["name"] = (
                f"{dynamic_resource['name']}_" f"{dynamic_resource_index}"
            )
            # Adding dynamic resource to list
            dynamic_resources[dynamic_resource["name"]] = RESOURCE_MAP[
                dynamic_resource["type"]
            ](
                **dynamic_resource,
                order_index=order_index,
            )
        # Indexed resource name of the dynamic resource
        indexed_resource_name = f"{resource_name}_{dynamic_resource_index}"
        resource: Resource = dynamic_resources[indexed_resource_name]
        # Appending resource to required list of parent resource
        parent_resource.requires.append(indexed_resource_name)
        print("Parent resource requirements: ", parent_resource.requires)

        def _add_child_resource(resource: Resource) -> None:
            """
            Recursively adds a child resource to the resources list
            """
            print("Start of add child resource")
            self._resources[resource.name] = resource
            for req in resource.requires:
                _add_child_resource(dynamic_resources[req])

        _add_child_resource(resource)
        # Initialize the resource graph again with the update resources
        self._initialize_resource_graph()
        self._find_current_resource()

    def hotword_activated(self) -> None:
        self._in_this_dialogue = True
        print("In hotword activated")
        self.setup_resources()

    def pause_dialogue(self) -> None:
        ...  # TODO

    def resume_dialogue(self) -> None:
        ...  # TODO

    def not_in_dialogue(self) -> bool:
        """Check if the client is in or wants to start this dialogue"""
        return not self._in_this_dialogue

    @property
    def dialogue_name(self) -> Optional[str]:
        if hasattr(self, "_dialogue_name"):
            return self._dialogue_name
        return None

    @property
    def current_resource(self) -> Resource:
        if self._current_resource is None:
            self._current_resource = self._find_current_resource()
        return self._current_resource

    def get_resource(self, name: str) -> Resource:
        try:
            return self._resources[name]
        except KeyError:
            raise ResourceNotFoundError(f"Resource {name} not found")

    @property
    def extras(self) -> Dict[str, Any]:
        return self._extras

    @property
    def timed_out(self) -> bool:
        return self._timed_out

    def get_descendants(
        self, resource: Resource, filter_func: Optional[FilterFuncType] = None
    ) -> List[Resource]:
        """
        Given a resource and an optional filter function
        (with a resource and the depth in tree as args, returns a boolean),
        returns all descendants of the resource that match the function
        (all of them if filter_func is None).
        Returns the descendants in preorder
        """
        descendants: List[Resource] = []

        def _recurse_descendants(
            resource: Resource, depth: int, filter_func: FilterFuncType
        ) -> None:
            nonlocal descendants
            for child in self._resource_graph[resource]["children"]:
                if filter_func(child, depth):
                    descendants.append(child)
                _recurse_descendants(child, depth + 1, filter_func)

        _recurse_descendants(resource, 0, filter_func or _ALLOW_ALL_FILTER)
        return descendants

    def get_children(self, resource: Resource) -> List[Resource]:
        """Given a resource, returns all children of the resource"""
        return self._resource_graph[resource]["children"]

    def get_ancestors(
        self, resource: Resource, filter_func: Optional[FilterFuncType] = None
    ) -> List[Resource]:
        """
        Given a resource and an optional filter function
        (with a resource and the depth in tree as args, returns a boolean),
        returns all ancestors of the resource that match the function
        (all of them if filter_func is None).
        """
        ancestors: List[Resource] = []

        def _recurse_ancestors(
            resource: Resource, depth: int, filter_func: FilterFuncType
        ) -> None:
            nonlocal ancestors
            for parent in self._resource_graph[resource]["parents"]:
                if filter_func(parent, depth):
                    ancestors.append(parent)
                _recurse_ancestors(parent, depth + 1, filter_func)

        _recurse_ancestors(resource, 0, filter_func or _ALLOW_ALL_FILTER)
        return ancestors

    def get_parents(self, resource: Resource) -> List[Resource]:
        """Given a resource, returns all parents of the resource"""
        return self._resource_graph[resource]["parents"]

    def get_answer(
        self, answering_functions: AnsweringFunctionMap, result: Any
    ) -> Optional[AnswerTuple]:
        if self._answer_tuple is not None:
            return self._answer_tuple
        self._current_resource = self._find_current_resource()
        self._answering_functions = answering_functions

        # Check if dialogue was cancelled # TODO: Change this (have separate cancel method)
        if self._current_resource.is_cancelled:
            self._answer_tuple = self._answering_functions[_FINAL_RESOURCE_NAME](
                self._current_resource, self, result
            )
            if not self._answer_tuple:
                raise ValueError("No answer for cancelled dialogue")
            return self._answer_tuple

        resource_name = self._current_resource.name.split("_")[0]
        if resource_name in self._answering_functions:
            print("GENERATING ANSWER FOR ", resource_name)
            ans = self._answering_functions[resource_name](
                self._current_resource, self, result
            )
            return ans
        # Iterate through resources (postorder traversal)
        # until one generates an answer
        self._answer_tuple = self._get_answer(self._current_resource, result, set())

        return self._answer_tuple

    # TODO: Can we remove this function?
    def _get_answer(
        self, curr_resource: Resource, result: Any, finished: Set[Resource]
    ) -> Optional[AnswerTuple]:
        for resource in self._resource_graph[curr_resource]["children"]:
            if resource not in finished:
                finished.add(resource)
                ans = self._get_answer(resource, result, finished)
                if ans:
                    return ans
        if curr_resource.name in self._answering_functions:
            return self._answering_functions[curr_resource.name](
                curr_resource, self, result
            )
        return None

    def set_answer(self, answer: AnswerTuple) -> None:
        self._answer_tuple = answer

    def set_resource_state(self, resource_name: str, state: ResourceState):
        """
        Set the state of a resource.
        Sets state of all parent resources to unfulfilled
        if cascade_state is set to True for the resource.
        """
        resource = self._resources[resource_name]
        lowered_state = resource.state > state
        resource.state = state
        if resource.cascade_state and lowered_state:
            # Find all parent resources and set to corresponding state
            ancestors = set(self.get_ancestors(resource))
            for anc in ancestors:
                anc.state = ResourceState.UNFULFILLED

    def _find_current_resource(self) -> Resource:
        """
        Finds the current resource in the resource graph
        using a postorder traversal of the resource graph.
        """
        curr_res: Optional[Resource] = None
        finished_resources: Set[Resource] = set()

        def _recurse_resources(resource: Resource) -> None:
            nonlocal curr_res, finished_resources
            finished_resources.add(resource)
            if resource.is_confirmed or resource.is_skipped:
                # Don't set resource as current if it is confirmed or skipped
                return
            # Current resource is neither confirmed nor skipped,
            # so we try to find candidates lower in the tree first
            for child in self._resource_graph[resource]["children"]:
                if child not in finished_resources:
                    _recurse_resources(child)  # TODO: Unwrap recursion?
                if curr_res is not None:
                    # Found a suitable resource, stop looking
                    return
            curr_res = resource
            while not curr_res.prefer_over_wrapper:
                wrapper_parents = [
                    par
                    for par in self._resource_graph[curr_res]["parents"]
                    if isinstance(par, WrapperResource)
                ]
                assert (
                    len(wrapper_parents) <= 1
                ), "A resource cannot have more than one wrapper parent"
                if wrapper_parents:
                    curr_res = wrapper_parents[0]
                else:
                    break

        _recurse_resources(self._resources["Final"])
        return curr_res or self._resources["Final"]

    # TODO: Can we move this function into set_resource_state?
    def skip_other_resources(self, or_resource: OrResource, resource: Resource) -> None:
        """Skips other resources in the or resource"""
        # TODO: Check whether OrResource is exclusive or not
        assert isinstance(
            or_resource, OrResource
        ), f"{or_resource} is not an OrResource"
        for res in or_resource.requires:
            if res != resource.name:
                self.set_resource_state(res, ResourceState.SKIPPED)

    # TODO: Can we move this function into set_resource_state?
    def update_wrapper_state(self, wrapper: WrapperResource) -> None:
        """
        Updates the state of the wrapper resource
        based on the state of its children.
        """
        print("UPDATING WRAPPER STATE", wrapper.state)
        if wrapper.state == ResourceState.UNFULFILLED:
            print("Wrapper is unfulfilled")
            if all(
                [
                    child.state == ResourceState.UNFULFILLED
                    for child in self._resource_graph[wrapper]["children"]
                ]
            ):
                print("All children are unfulfilled")
                return
            print("At least one child is fulfilled")
            self.set_resource_state(wrapper.name, ResourceState.PARTIALLY_FULFILLED)
        elif wrapper.state == ResourceState.PARTIALLY_FULFILLED:
            print("Wrapper is partially fulfilled")
            if any(
                [
                    child.state != ResourceState.CONFIRMED
                    for child in self._resource_graph[wrapper]["children"]
                ]
            ):
                print("At least one child is not confirmed")
                self.set_resource_state(wrapper.name, ResourceState.PARTIALLY_FULFILLED)
                return
            print("All children are confirmed")
            self.set_resource_state(wrapper.name, ResourceState.FULFILLED)

    def finish_dialogue(self) -> None:
        """Set the dialogue as finished."""
        self._finished = True

    def serialize_data(self) -> Dict[str, Optional[str]]:
        """Serialize the dialogue's data for saving to database"""
        if self._resources[_FINAL_RESOURCE_NAME].is_confirmed:
            # When final resource is confirmed, the dialogue is over
            self.finish_dialogue()
        ds_json: Optional[str] = None
        if not self._finished and not self._timed_out:
            print("!!!!!!!!!!!!!!!Serializing data! with resources: ", self._resources)
            ds_json = json.dumps(
                {
                    _RESOURCES_KEY: self._resources,
                    _MODIFIED_KEY: datetime.datetime.now(),
                    _EXTRAS_KEY: self._extras,
                },
                cls=DialogueJSONEncoder,
            )
        # Wrap data before saving dialogue state into client data
        # (due to custom JSON serialization)
        cd: Dict[str, Optional[str]] = {self._dialogue_name: ds_json}
        return cd
