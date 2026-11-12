fetch('http://01.02.03.40:5900/api/get_subsystem_filenames',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_name:'SAMPLE'})}).then (response=>response.json()).then(data=>console.log(data)).catch(error=>console.error('Error:',error));


{'data':{'POWER':['ab-abc.tst','bc-bst.tst',..........],'ILC':['ab-sdc.tst','rc-bst.tst',..........],'RSU':['GH-sdc.tst','DF-bst.tst',..........]}}



//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
Yes! You can test the API separately without running your Flask application.

The easiest way is to use Python, since your project itself uses Python.

### Option 1: Simple Python test (recommended)

Create a new file named `test_api.py` and paste this code:

Python


................................................................................................

import requests
import json

API_URL = "http://01.02.03.40:5900/api/get_subsystem_filenames"

project_name = "SAMPLE"

try:
    response = requests.post(
        API_URL,
        json={
            "project_name": project_name
        },
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    print("\n========== API RESPONSE ==========\n")

    print(json.dumps(data, indent=4))

    print("\n========== SUBSYSTEMS ==========\n")

    for subsystem, filenames in data["data"].items():

        print("Subsystem:", subsystem)

        for filename in filenames:
            print("  -", filename)

        print()

except requests.exceptions.RequestException as error:
    print("API connection error:", error)

except (ValueError, KeyError, TypeError) as error:
    print("Invalid API response:", error)


.....................................................................................

### Option 2: How to execute it

Open your terminal in the folder containing `test_api.py`.

First, install requests if necessary:

Bash

```
pip install requests
```

Then execute:

Bash

```
python test_api.py
```

### Expected output

If the API works and returns the expected response, you should see something like:

Example output

```
========== API RESPONSE ==========

{
    "data": {
        "POWER": [
            "ab-abc.tst",
            "bc-bst.tst"
        ],
        "ILC": [
            "ab-sdc.tst",
            "rc-bst.tst"
        ],
        "RSU": [
            "GH-sdc.tst",
            "DF-bst.tst"
        ]
    }
}

========== SUBSYSTEMS ==========

Subsystem: POWER
  - ab-abc.tst
  - bc-bst.tst

Subsystem: ILC
  - ab-sdc.tst
  - rc-bst.tst
```

Illustrative output only. Actual subsystem names and filenames depend on the API.

### What does this test confirm?

* Whether the API server is reachable.

* Whether the API accepts your project name.

* Whether the API returns a valid JSON response.

* Whether subsystem names and their filenames are being received correctly.

My suggestion: Run `test_api.py` first, before integrating the API into `app.py`. If it returns the expected subsystem data, you can move on to testing the complete dashboard.

If you get an error, share the complete terminal output with me and I'll help you identify the issue.


  -----------------------------------------

  Yes! Exactly. You can use this `test_api.py` code to test your API independently.

If the API URL is correct, the server is running, and the API accepts the `SAMPLE` project name, you should receive the subsystem data in this format:

JSON

```
{
    "data": {
        "POWER": [
            "ab-abc.tst",
            "bc-bst.tst"
        ],
        "ILC": [
            "ab-sdc.tst",
            "rc-bst.tst"
        ],
        "RSU": [
            "GH-sdc.tst",
            "DF-bst.tst"
        ]
    }
}
```

Just remember: This is an example of the expected output, not a guaranteed response. The actual data comes from your API.

Ready to test

Run:

Bash

```
python test_api.py
```

If you get the actual subsystem names and filenames printed, your API test is successful!
