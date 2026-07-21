# Nexora Runtime smoke test

Run all commands from `/workspace`.

## Create the local environment

```sh
python3 -c "import urllib.request; urllib.request.urlretrieve('https://bootstrap.pypa.io/virtualenv.pyz', 'nexora/runtime/.virtualenv.pyz')"
python3 nexora/runtime/.virtualenv.pyz nexora/runtime/.venv
rm nexora/runtime/.virtualenv.pyz
```

## Install pinned dependencies

```sh
nexora/runtime/.venv/bin/python -m pip install --requirement nexora/runtime/requirements.txt
```

## Verify Python and imports

```sh
nexora/runtime/.venv/bin/python --version
nexora/runtime/.venv/bin/python -c "import yaml; import jsonschema"
```

## Run the internal test

```sh
nexora/runtime/.venv/bin/python -m nexora.runtime.run_internal_runtime_test
```
