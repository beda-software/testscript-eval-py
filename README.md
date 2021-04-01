# testscript-eval-py
## Tests
To run tests locally, copy `.env.tpl` to `.env` and specify `TESTS_AIDBOX_LICENSE_ID` and `TESTS_AIDBOX_LICENSE_KEY`.  
You can get key and id from the https://license-ui.aidbox.app/


Run Aidbox`docker-compose -f docker-compose.tests.yaml up -d`.


Run tests ```
PYTHONPATH='.' pytest
````
