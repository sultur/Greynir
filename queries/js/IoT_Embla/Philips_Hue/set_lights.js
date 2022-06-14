"use strict";

// Constants to be used when setting lights from HTML
// var BRIDGE_IP = "192.168.1.68";
// var USERNAME = "MQH9DVv1lhgaOKN67uVox4fWNc9iu3j5g7MmdDUr";

// TODO: Implement a hotfix for Ikea Tradfri bulbs, since it can only take one argument at a time

/** Gets a target for the given query and sets the state of the target to the given state using a fetch request.
 *  @param {String} query - the query to find the target e.g. "eldhús" or "lampi"
 *  @param {String} state - the state to set the target to e.g. "{"on": true}" or "{"scene": "energize"}"
 */
function setLights(query, state) {
    let parsedState = JSON.parse(state);
    let promiseList;
    try {
        promiseList = [getAllGroups(), getAllLights()];
    } catch (err) {
        console.log(err);
        console.log("Failed to get light and groups functions.");
        fetch(`http://192.168.1.70:9001`, {
            method: "POST",
            body: JSON.stringify({
                error: "Failed to get light and groups functions.",
                error_message: err.toString(),
            }),
        });
    }
    let sceneName;
    if (parsedState.scene) {
        sceneName = parsedState.scene;
        try {
            promiseList.push(getAllScenes());
        } catch (err) {
            console.log(err);
            console.log("Failed to get scene function.");
            fetch(`http://192.168.1.70:9001`, {
                method: "POST",
                body: JSON.stringify({
                    error: "Failed to get scene function.",
                    error_message: err.toString(),
                }),
            });
        }
    }
    // Get all lights and all groups from the API (and all scenes if "scene" was a paramater)
    Promise.allSettled(promiseList)
        .then((resolvedPromises) => {
            let allGroups = resolvedPromises[0].value;
            let allLights = resolvedPromises[1].value;
            // if (Array.isArray(allGroups)) {
            //     throw "Failed to get groups.";
            // }
            // if (Array.isArray(allLights)) {
            //     throw "Failed to get lights.";
            // }
            let allScenes;
            try {
                allScenes = resolvedPromises[2].value;
            } catch (e) {
                console.log("No scene in state");
            }
            for (i in resolvedPromises) {
                if (Array.isArray(resolvedPromises[i].value)) {
                    throw `${resolvedPromises[i].value.name} returns array.`;
                }
            }
            // Get the target object for the given query
            let targetObject = getTargetObject(query, allLights, allGroups);
            console.log("targetObject: ", targetObject);
            if (targetObject === undefined) {
                return "Ekki tókst að finna ljós";
            }
            // Check if state includes a scene or a brightness change
            if (sceneName) {
                let sceneID = getSceneID(parsedState.scene, allScenes);
                if (sceneID === undefined) {
                    return "Ekki tókst að finna senu";
                } else {
                    parsedState.scene = sceneID; // Change the scene parameter to the scene ID
                    state = JSON.stringify(parsedState);
                }
            }
            else if (parsedState.bri_inc) {
                state = JSON.stringify(parsedState);
            }
            // Send data to API
            let url = targetObject.url;
            fetch(`http://${BRIDGE_IP}/api/${USERNAME}/${url}`, {
                method: "PUT",
                body: state,
            })
                .then((resp) => resp.json())
                .then((obj) => {
                    console.log(obj);
                })
                .catch((err) => {
                    console.log("an error occurred!");
                });
        })
        .catch((err) => {
            console.log(err);
            console.log("Large promise failed.");
            fetch(`http://192.168.1.70:9001`, {
                method: "POST",
                body: JSON.stringify({
                    error: "Large promise failed.",
                    error_message: err.toString(),
                }),
            });
        });
}

/** Finds a matching light or group and returns an object with the ID, name and url for the target
 * @param {String} query - the query to find the target e.g. "eldhús"
 * @param {Array} allLights - an object of all lights from the API
 * @param {Array} allGroups - an object of all groups from the API
 */
function getTargetObject(query, allLights, allGroups) {
    let targetObject, selection, url;
    let lightsResult = philipsFuzzySearch(query, allLights);
    let groupsResult = philipsFuzzySearch(query, allGroups);

    if (lightsResult != null && groupsResult != null) {
        // Found a match for a light group and a light
        selection =
            lightsResult.score < groupsResult.score // Select the light with the highest score
                ? lightsResult
                : groupsResult;
        url =
            selection === lightsResult // Set url based on selection
                ? `lights/${lightsResult.result.ID}/state`
                : `groups/${groupsResult.result.ID}/action`;
    } else if (lightsResult != null && groupsResult == null) {
        // Found a match for a single light
        selection = lightsResult;
        url = `lights/${selection.result.ID}/state`;
    } else if (groupsResult != null && lightsResult == null) {
        // Found a match for a light group
        selection = groupsResult;
        url = `groups/${selection.result.ID}/action`;
    } else {
        return;
    }

    targetObject = {
        id: selection.result.ID,
        url: url,
    };
    return targetObject;
}

/** Returns the ID for a given scene name using fuzzy search
 * @param {String} sceneName - the name of the scene to find
 * @param {Object} allScenes - an array of all scenes from the API
 */
function getSceneID(scene_name, allScenes) {
    let scenesResult = philipsFuzzySearch(scene_name, allScenes);
    console.log("sceneResult :", scenesResult);
    if (scenesResult != null) {
        return scenesResult.result.ID;
    } else {
        return;
    }
}

/* Tester function for setting lights directly from HTML controls */
function setLightsFromHTML() {
    let query = document.getElementById("queryInput").value;
    let stateObject = new Object();
    stateObject.bri_inc = Number(
        document.getElementById("brightnessInput").value
    );
    stateObject = JSON.stringify(stateObject);
    setLights(query, stateObject);
}

/* Tester function for setting lights directly from HTML input fields */
function queryTestFromHTML() {
    let query = document.getElementById("queryInput").value;
    let bool = document.getElementById("boolInput").value;
    let scene = document.getElementById("sceneInput").value;
    console.log(query);
    if (scene === "") {
        setLights(query, `{"on": ${bool}}`);
    } else {
        setLights(query, `{"scene": "${scene}"}`);
    }
}

// /** Finds a matching light or group and returns an object with the ID, name and url for the target
//  * @param {String} query - the query to find the target e.g. "eldhús"
//  * @param {Object} allLights - an array of all lights from the API
//  * @param {Object} allGroups - an array of all groups from the API
//  */
//  function getTargetObjectOLD(query, allLights, allGroups) {
//     let targetObject;
//     let lightsResult = philipsFuzzySearch(query, allLights);
//     let groupsResult = philipsFuzzySearch(query, allGroups);
//     console.log("lightsResult: ", lightsResult);
//     console.log("groupsResult: ", groupsResult);

//     if (lightsResult != null && groupsResult == null) {
//         // Found a match for a single light
//         targetObject = {
//             id: lightsResult.result.ID,
//             type: "light",
//             url: `lights/${lightsResult.result.ID}/state`,
//         };
//     } else if (groupsResult != null && lightsResult == null) {
//         // Found a match for a light group
//         targetObject = {
//             id: groupsResult.result.ID,
//             type: "group",
//             url: `groups/${groupsResult.result.ID}/action`,
//         };
//     } else if (groupsResult != null && lightsResult != null) {
//         let lightsScore = lightsResult.score;
//         let groupsScore = groupsResult.score;
//         let selection = lightsScore > groupsScore ? lightsResult : groupsResult;
//         console.log("selection :", selection);
//         // Found a match for a light group and a light
//         targetObject = {
//             id: lightsResult.result.ID,
//             type: "light",
//             url: `lights/${lightsResult.result.ID}/state`,
//         };
//     }
//     console.log("targetObject: ", targetObject);
//     return targetObject;
// }
