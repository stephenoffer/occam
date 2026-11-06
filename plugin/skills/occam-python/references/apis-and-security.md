# Python APIs that moved, and security sinks

## Check the version before trusting memory

Recalled APIs lag behind releases. Check the supported Python in `requires-python` and CI, and the installed version of a library with `python -c "import importlib.metadata as m; print(m.version('pydantic'))"`, then read the documentation for that version. Run tests with `-W error::DeprecationWarning` to find what is already on its way out. Ruff's `UP`, `DTZ`, `NPY` and `PD` rules catch many of these, targeted by `target-version`.

This list is a starting point, not a substitute for checking.

| From memory | Status | Instead |
|---|---|---|
| `datetime.utcnow()`, `utcfromtimestamp()` | Deprecated in 3.12, and naive | `datetime.now(timezone.utc)`, `fromtimestamp(x, timezone.utc)` |
| `asyncio.get_event_loop()` with no running loop | `RuntimeError` on 3.14 | `asyncio.run()`, `asyncio.get_running_loop()` |
| `@asyncio.coroutine` | Removed in 3.11 | `async def` |
| `collections.Mapping` and similar | Removed in 3.10 | `collections.abc` |
| `imp`, `asyncore`, `asynchat`, `smtpd`, `distutils` | Removed in 3.12 | `importlib`, `asyncio`, `setuptools` or `packaging` |
| `cgi`, `cgitb`, `pipes`, `telnetlib`, `crypt`, `nntplib` | Removed in 3.13 | See PEP 594 |
| `assertEquals`, `assertRegexpMatches` | Removed in 3.12 | `assertEqual`, `assertRegex` |
| `pkg_resources` | Deprecated, and absent from current setuptools | `importlib.metadata`, `importlib.resources` |
| `typing.List`, `typing.Dict` | Deprecated aliases that still work | `list[int]` from 3.9, `X \| None` from 3.10, as the supported versions allow |
| Pydantic `.dict()`, `.json()`, `.parse_obj()`, `@validator`, `@root_validator`, `class Config`, `orm_mode` | Pydantic v1 | `.model_dump()`, `.model_dump_json()`, `.model_validate()`, `@field_validator`, `@model_validator`, `model_config`, `from_attributes` |
| `from pydantic import BaseSettings` | Moved in Pydantic v2 | The `pydantic-settings` package |
| `openai.ChatCompletion.create()` | Pre-1.0 client | `OpenAI().chat.completions.create()` |
| pandas `DataFrame.append` | Removed in 2.0 | `pd.concat` |
| NumPy `np.float`, `np.int`, `np.NaN` | Removed in 1.24, and 2.0 for `np.NaN` | `float`, `int`, `np.nan` |
| SQLAlchemy `session.query()`, `engine.execute()` | Legacy and removed in 2.0 | `select()`, `connection.execute()` |
| `pytz` timezones passed as `tzinfo=` | Silently wrong: gives a historical local mean time offset | `zoneinfo`, from 3.9 |
| `python setup.py install`, `python setup.py test` | Deprecated | `pip install .`, `python -m pytest` |

A guessed package name is worse than a stale API, because installing it runs someone else's code. Confirm it exists and is the one you mean first. The core skill's design reference covers vetting.

## Security sinks

The general checks are in the core skill's security reference. These are the Python spellings, most of which Ruff's `S` rules can find. Each is a lead until you confirm that untrusted data reaches it.

| Sink | Why it is a problem | Instead |
|---|---|---|
| `pickle`, `shelve`, `joblib.load`, `torch.load`, `pandas.read_pickle`, `numpy.load(allow_pickle=True)` | Loading can run code | JSON or another data format, or `torch.load(weights_only=True)` |
| `yaml.load` with `Loader`, `UnsafeLoader` or `FullLoader` | Can build objects from the input, depending on the loader and version | `yaml.safe_load` |
| `eval`, `exec` | Run whatever they are given | `ast.literal_eval` for literals, or a dispatch table |
| `subprocess` with `shell=True`, `os.system` | Shell injection | An argument list, with `shell=False` |
| `cursor.execute(f"...")` | SQL injection | Bound parameters. `sqlalchemy.text()` with `bindparams` |
| `tarfile.extractall`, `shutil.unpack_archive` | Traversal and link attacks. The safe filter is the default only from 3.14 | `filter="data"`, added in 3.12 and backported to some earlier patch releases. It doesn't stop decompression bombs |
| `os.path.join(root, name)` with outside input | An absolute `name` discards `root`, and `..` escapes it | `Path(root, name).resolve().is_relative_to(Path(root).resolve())` |
| `random` for tokens | Predictable | `secrets` |
| `==` on secrets | Timing leak | `hmac.compare_digest` |
| `hashlib.md5` or `sha256` on passwords | Too fast to resist guessing | argon2, scrypt or bcrypt through a maintained library |
| `tempfile.mktemp` | Race on the name | `mkstemp`, `NamedTemporaryFile` |
| `requests` with `verify=False` or no `timeout` | No certificate check. `requests` has no default timeout, so a call can hang | Keep verification on, and always pass `timeout=` |
| `xml.etree`, `xml.dom`, `xml.sax` on untrusted XML | Entity expansion attacks, depending on the bundled Expat version | `defusedxml` |
| Jinja2 `Environment()` | Autoescaping is off by default | `autoescape=select_autoescape()` |
| Jinja2 `from_string()` on outside input | Template injection runs code, even with autoescaping | A fixed template with the input as data. `SandboxedEnvironment` if users really write templates |
| `assert` for an authorization check | `-O` removes it | Raise a real error |

## Logging

Use `logger.exception` inside `except` to keep the traceback, and `logger.info("x=%s", x)` so that formatting is skipped when the level is off. Keep secrets, tokens and personal data out of log messages, `repr` output and exception text.
