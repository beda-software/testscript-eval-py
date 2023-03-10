# testscript-eval-py
## Tests
To run tests locally specify `TESTS_AIDBOX_LICENSE` in the `.env` file
You can get license from the https://aidbox.app/ui/portal/

Run Aidbox`docker compose up -d`.

Install project dependencies: `pipenv install --dev`

Run `echo PYTHONPATH=. >> .env` to run tests properly

Run tests ```
pipenv run pytest
````
