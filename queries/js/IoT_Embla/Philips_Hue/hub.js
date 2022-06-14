"use strict";

async function findHub() {
    fetch(`http://192.168.1.70:9001`, {
        method: "POST",
        body: JSON.stringify({ function: "findHub" }),
    });
    let hubObj = {
        id: "ecb5fafffe1be1a4",
        internalipaddress: "192.168.1.68",
        port: "443",
    };
    console.log(JSON.stringify(hubObj));
    return hubObj;
    return fetch(`https://discovery.meethue.com`)
        .then((resp) => resp.json())
        .then((obj) => {
            console.log(obj);
            return obj[0];
        })
        .catch((err) => {
            console.log(err.message);
            console.log("Failed to discover hub.");
            fetch(`http://192.168.1.70:9001`, {
                method: "POST",
                body: JSON.stringify({
                    error: "Failed to discover hub.",
                    error_message: err.message,
                }),
            });
        });
}

async function createNewDeveloper(ipAddress) {
    fetch(`http://192.168.1.70:9001`, {
        method: "POST",
        body: JSON.stringify({ function: "createNewDeveloper" }),
    });
    console.log("create new developer at " + ipAddress);
    try {
        fetch(`http://192.168.1.70:9001`, {
            method: "POST",
            body: JSON.stringify({
                msg: "fetch success.",
            }),
        })
            .then((x) => console.log("fetch test virkar"))
            .catch((err) => {
                console.log("fetch test virkar ekki");
                console.log(typeof err, err.stack);
            });
    } catch (err) {
        console.log("Fetch wrapper error caught.");
        console.log(err.name);
    }
    return fetch(`http://${ipAddress}/api`, {
        method: "POST",
        body: JSON.stringify({
            devicetype: "mideind_hue_communication#smartdevice",
        }),
    })
        .then((resp) => {
            console.log(resp.status);
            return resp.json();
        })
        .then((obj) => {
            console.log(JSON.stringify(obj));
            return obj[0];
        })
        .catch((err) => {
            console.log(err.message);
            console.log("Failed to create new developer.");
            fetch(`http://192.168.1.70:9001`, {
                method: "POST",
                body: JSON.stringify({
                    error: "Failed to create new developer.",
                    error_message: err.message,
                }),
            });
        });
}

async function storeDevice(data, requestURL) {
    fetch(`http://192.168.1.70:9001`, {
        method: "POST",
        body: JSON.stringify({ function: "storeDevice" }),
    });
    console.log("store device");
    return fetch(`http://${requestURL}/register_query_data.api`, {
        method: "POST",
        body: JSON.stringify(data),
        headers: {
            "Content-Type": "application/json",
        },
    })
        .then((resp) => resp.json())
        .then((obj) => {
            return obj;
        })
        .catch((err) => {
            console.log(err);
            console.log("Failed to store device.");
            fetch(`http://192.168.1.70:9001`, {
                method: "POST",
                body: JSON.stringify({
                    error: "Failed to store device.",
                    error_message: err.message,
                }),
            });
        });
}

// clientID = "82AD3C91-7DA2-4502-BB17-075CEC090B14", requestURL = "192.168.1.68")
async function connectHub(clientID, requestURL) {
    fetch(`http://192.168.1.70:9001`, {
        method: "POST",
        body: JSON.stringify({ function: "connectHub" }),
    });
    console.log("connect hub");
    let deviceInfo = await findHub();
    console.log("hello word.");
    console.log("device_info: ", JSON.stringify(deviceInfo));
    console.log("device_ip :", deviceInfo.internalipaddress);

    try {
        let username = await createNewDeveloper(deviceInfo.internalipaddress);
        console.log("username: ", username);
        if (!username.success) {
            return "Ýttu á 'Philips' takkann á tengiboxinu og reyndu aftur";
        }

        let data = {
            client_id: clientID,
            key: "smartlights",
            data: {
                smartlights: {
                    selected_light: "philips_hue",
                    philips_hue: {
                        username: username.success.username,
                        ipAddress: deviceInfo.internalipaddress,
                    },
                },
            },
        };

        let result = await storeDevice(data, requestURL);
        console.log("result: ", result);
        return "Tenging við snjalltæki tókst";
    } catch (err) {
        console.log(err.message);
        console.log("Failed to connect to smart device.");
        fetch(`http://192.168.1.70:9001`, {
            method: "POST",
            body: JSON.stringify({
                error: "Failed to connect to smart device.",
                error_message: err.message,
            }),
        });
        return "Ekki tókst að tengja snjalltæki.";
    }
}

function syncConnectHub(clientID, requestURL) {
    // let x = new XMLHttpRequest();
    // x.open("GET", `http://192.168.1.70:9001`);
    // x.send();
    console.log(fetch.toString());
    fetch(`http://192.168.1.70:9001`, {
        method: "POST",
        body: JSON.stringify({ function: "syncConnectHub" }),
    });
    connectHub(clientID, requestURL);
    return "Reyndi að tengjast Philips Hub";
    // return clientID;
}

function syncConnectHubFromHTML() {
    fetch(`http://192.168.1.70:9001`, {
        method: "POST",
        body: JSON.stringify({ function: "syncConnectHubFromHTML" }),
    });
    let clientID = "82AD3C91-7DA2-4502-BB17-075CEC090B14";
    let requestURL = "192.168.1.69:5000";
    connectHub(clientID, requestURL);
    return clientID;
}
