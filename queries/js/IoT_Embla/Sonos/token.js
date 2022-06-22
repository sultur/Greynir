function createToken() {
    let myHeaders = new Headers();
    myHeaders.append(
        "Authorization",
        "Basic NTViYjcyODAtMmYxYi00YjBkLWE0MDgtODA2ZDIzZDg1YTEyOjM3ODE3MzQ5LTdjZDEtNDYwZC1hYTBhLWJlYWQzYTQwMjBmMw=="
    );
    myHeaders.append("Cookie", "JSESSIONID=A6CEA429EB040B1573FB5052CB3C6EF4");

    let requestOptions = {
        method: "POST",
        headers: myHeaders,
        redirect: "follow",
    };

    fetch(
        "https://api.sonos.com/login/v3/oauth/access?grant_type=authorization_code&code=CepUJVL4&redirect_uri=http://localhost:5000",
        requestOptions
    )
        .then((response) => response.text())
        .then((result) => console.log(result))
        .catch((error) => console.log("error", error));
}
