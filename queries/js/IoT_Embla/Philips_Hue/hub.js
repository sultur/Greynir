"use strict";

async function findHub() {
    fetch(`http://192.168.1.70:9001`, {
        method: "POST",
        body: JSON.stringify({ function: "findHub" }),
    });
    // let hubArr = [];
    // let hubObj = new Object();
    // hubObj.id = "ecb5fafffe1be1a4";
    // hubObj.internalipaddress = "192.168.1.68";
    // hubObj.port = "443";
    // console.log(hubObj);
    // hubArr.push(hubObj);
    // return hubArr[0];
    return fetch(`https://discovery.meethue.com`)
        .then((resp) => resp.json())
        .then((obj) => {
            console.log(obj);
            return obj[0];
        })
        .catch((err) => {
            console.log("No smart device found!");
        });
}

async function createNewDeveloper(ipAddress) {
    fetch(`http://192.168.1.70:9001`, {
        method: "POST",
        body: JSON.stringify({ function: "createNewDeveloper" }),
    });
    console.log("create new developer");
    return fetch(`http://${ipAddress}/api`, {
        method: "POST",
        body: JSON.stringify({
            devicetype: "mideind_hue_communication#smartdevice",
        }),
    })
        .then((resp) => resp.json())
        .then((obj) => {
            return obj[0];
        })
        .catch((err) => {
            console.log(err);
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
            console.log("Error while storing user");
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
    console.log("device info: ", deviceInfo);
    console.log("device_ip :", deviceInfo.internalipaddress);

    try {
        let username = await createNewDeveloper(deviceInfo.internalipaddress);
        console.log("username: ", username);
        if (!username.success) {
            return "Ýttu á 'Philips' takkann á tengiboxinu og reyndu aftur";
        }

        const data = {
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

        const result = await storeDevice(data, requestURL);
        console.log("result: ", result);
        return "Tenging við snjalltæki tókst";
    } catch (error) {
        console.log(error);
        return "Ekki tókst að tengja snjalltæki";
    }
}

function syncConnectHub(clientID, requestURL) {
    let x = new XMLHttpRequest();
    x.open("GET", `http://192.168.1.70:9001`);
    x.send();
    fetch(`http://192.168.1.70:9001`, {
        method: "POST",
        body: JSON.stringify({ function: "syncConnectHub" }),
    });
    connectHub(clientID, requestURL);
    return clientID;
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
