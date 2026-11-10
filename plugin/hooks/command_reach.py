"""Where a command's effect lands beyond this machine's work: production data, an account, project or cluster switched to earlier, another
host or a public registry, and a package nothing here declares. One-time notes, never holds, each with what to check before it runs.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Callable, NamedTuple

SCRIPTS = str(Path(__file__).resolve().parents[1] / "skills" / "occam" / "scripts")  # occam_tools, which reads the manifests
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from destructive import names_production  # noqa: E402
from occam_commands import option_value, settings_of, subcommand  # noqa: E402


SERVER_ENVIRONMENT = re.compile(r"\b(?:RAILS_ENV|RACK_ENV|DJANGO_ENV|FLASK_ENV|APP_ENV|ENVIRONMENT|STAGE|ENV|MIX_ENV|SPRING_PROFILES_ACTIVE)=[\"']?(?:prod|production)\b"
                                 r"|-Dspring\.profiles\.active=(?:[\w-]*,)*(?:prod|production)\b|--spring\.profiles\.active=(?:[\w-]*,)*(?:prod|production)\b")
# A production env file sourced or loaded before the tests: `. ./.env.production`, `dotenv -e .env.prod`, `--env-file prod.env`.
PRODUCTION_ENV_FILE = re.compile(r"(?:^|[\s/=])(?:\.env[.-](?:prod|production)\b[\w.-]*|[\w.-]*\b(?:prod|production)\.env)(?=$|[\s;&|)])")


_TEST_RUNNERS = {"pytest", "py.test", "jest", "vitest", "mocha", "rspec", "phpunit"}
_TEST_SCRIPT = re.compile(r"^(?:test|tests|e2e|integration|it|spec|specs|acceptance)(?:$|[:_-])|[:_-](?:test|tests|e2e|integration|spec)(?:$|[:_-])", re.I)
_RUNS_TEST_FIRST = {"playwright": "test", "cypress": "run"}
_BUILD_TOOLS = {"mvn", "mvnw", "gradle", "gradlew"}
_BUILD_TEST_GOALS = re.compile(r"^(?:test|verify|integration-test|integrationTest|check|connectedCheck|-D(?:it\.)?test=.*)$")
_GOALS_THAT_TEST = {"mvn": {"package", "install", "deploy"}, "mvnw": {"package", "install", "deploy"}, "gradle": {"build"}, "gradlew": {"build"}}  # they run the tests too
_TASK_RUNNERS = {"make", "just", "task", "rake", "tox", "nox", "invoke"}
_LOAD_TESTERS = {"k6": "run", "locust": "", "artillery": "run", "vegeta": "attack", "wrk": "", "ab": "", "hey": "", "oha": "", "bombardier": "", "siege": "", "autocannon": "", "jmeter": ""}
# A host that says it isn't production. One that says nothing could be, so a load test aimed there gets a note.
_NOT_A_LIVE_HOST = re.compile(r"localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|\.local\b|\.test\b|\.example\b|(?:^|[.-])(?:staging|stage|stg|dev|develop|test|qa|uat|sandbox|preview|perf|load|loadtest|e2e)(?:[.-]|$)", re.I)
_SSH_VALUE_OPTIONS = {"-i", "-p", "-l", "-o", "-F", "-J", "-L", "-R", "-D", "-E", "-b", "-c", "-e", "-m", "-O", "-Q", "-S", "-W", "-w", "-B", "-I"}
_TEST_SUBCOMMAND = {"go", "cargo", "npm", "yarn", "pnpm", "bun", "rails", "mix", "dotnet"}
# A setting assigned in the command, read whole: the name says database, and the value names production as a word, as in `db.prod.internal`, not `products_test`.
_SETTING = re.compile(r"\b([A-Z_][A-Z0-9_]*)=(\S*)")
_DATABASE_NAME = re.compile(r"DATABASE|DB|POSTGRES|MYSQL|REDIS|MONGO|URL|URI|DSN|HOST|ENDPOINT|TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PROFILE|CONTEXT|PROJECT|ACCOUNT|CLUSTER")
_MANIFESTS = ("pyproject.toml", "requirements.txt", "requirements-dev.txt", "setup.py", "setup.cfg", "Pipfile", "package.json", "Cargo.toml", "go.mod")
_REGISTRY = {"pip": "pypi", "pip3": "pypi", "uv": "pypi", "poetry": "pypi", "pdm": "pypi", "pipenv": "pypi", "npm": "npm", "pnpm": "npm", "yarn": "npm", "bun": "npm", "cargo": "crates"}
_TOOLING = {"pip", "setuptools", "wheel", "uv", "pipx", "poetry", "virtualenv", "npm", "pnpm", "yarn"}  # upgrading the installer itself names nothing guessed
# Options that send a file: curl reads one for a value starting with @, whole for --data and the like, after the = for a form field, and before
# any = for --data-urlencode. wget's -T is a timeout, so each tool has its own.
_SENDS_FILE = {"curl": {"-T", "--upload-file"}, "wget": {"--post-file", "--body-file"}}
_READS_AT = {"-d", "--data", "--data-binary", "--json"}
_SHORT_WITH_VALUE = {"curl": "dFT", "wget": ""}


_TESTS_ON_PRODUCTION = "These tests are pointed at production, and tests create and delete data. Point them at an isolated database and account."


def _unwrapped(name: str, args: list[str]) -> tuple[str, list[str]]:
    """Past `bundle exec`, `uv run`, `npx` and `python -m`, to the program that really runs."""
    try:
        from occam_commands import run_by

        return run_by([name, *args])
    except Exception:  # occam: ignore[swallowed-exception] a note isn't worth failing a hook for
        return name, args


def runs_tests(words: list[str]) -> bool:
    """Does this step run tests, as against a build, a linter or a type checker? What a claim that tests pass needs."""
    return bool(words) and _runs_tests(words[0].rsplit("/", 1)[-1], words[1:])


def _runs_tests(name: str, args: list[str]) -> bool:
    name, args = _unwrapped(name, args)
    name, args, plain = _past_a_package_runner(name, args)
    if name in _RUNS_TEST_FIRST:
        return plain[:1] == [_RUNS_TEST_FIRST[name]]
    if name in _BUILD_TOOLS:
        excluded = {b for a, b in zip(args, args[1:]) if a in ("-x", "--exclude-task")} | {a.split("=", 1)[1] for a in args if a.startswith("--exclude-task=")}
        skipped = any("skipTests" in arg or "test.skip" in arg for arg in args) or any(task.rsplit(":", 1)[-1].lower().startswith(("test", "check")) for task in excluded)
        tasks = [arg.rsplit(":", 1)[-1] for arg in args if arg not in excluded]  # `:app:test` is the app project's test task
        return not skipped and any(_BUILD_TEST_GOALS.match(task) or task in _GOALS_THAT_TEST.get(name, ()) for task in tasks)
    if name in _TASK_RUNNERS:
        return any(_TEST_SCRIPT.search(arg) for arg in plain if "=" not in arg)
    if name in ("npm", "yarn", "pnpm", "bun") and _names_a_test_script(name, plain):
        return True
    return _a_test_runner(name, args)


def _past_a_package_runner(name: str, args: list[str]) -> tuple[str, list[str], list[str]]:
    """Past `npx`, `bunx`, `pnpx`, `pnpm exec` and `yarn exec`, to the program they run: its name, its arguments, and those that aren't options."""
    plain = [arg for arg in args if not arg.startswith("-")]
    if name in ("npx", "bunx", "pnpx") or (name in ("pnpm", "yarn") and plain[:1] == ["exec"]):
        rest = plain[1:] if plain[:1] == ["exec"] else plain
        if rest:
            name, args = rest[0], args[args.index(rest[0]) + 1:]
            plain = [arg for arg in args if not arg.startswith("-")]
    return name, args, plain


def _names_a_test_script(name: str, plain: list[str]) -> bool:
    script = plain[1] if plain[:1] == ["run"] and len(plain) > 1 else plain[0] if plain and name != "npm" else ""
    return bool(script and _TEST_SCRIPT.search(script))


def _a_test_runner(name: str, args: list[str]) -> bool:
    return (name in _TEST_RUNNERS or (name in _TEST_SUBCOMMAND and (args[:1] == ["test"] or args[:2] == ["run", "test"]))
            or (name.startswith("python") and args[:1] != [] and args[0].endswith("manage.py") and args[1:2] == ["test"]))


def _options(args: list[str], short: str) -> Iterator[tuple[str, str]]:
    """Each option with its value: `--data=@x`, `--data @x`, `-d@x`, `-d @x`, and a cluster such as `-sd @x`."""
    for index, arg in enumerate(args):
        following = args[index + 1] if index + 1 < len(args) else ""
        if arg.startswith("--"):
            flag, joined, value = arg.partition("=")
            yield flag, value if joined else following
        elif arg.startswith("-") and len(arg) > 1:
            at = next((position for position, letter in enumerate(arg[1:], 1) if letter in short), None)
            if at is not None:
                yield "-" + arg[at], arg[at + 1:] or following


def _file_sent(name: str, flag: str, value: str) -> str:
    if flag in _SENDS_FILE[name]:
        return value
    if flag in _READS_AT and value.startswith("@"):
        return value[1:]
    if flag in ("-F", "--form"):
        field = value.partition("=")[2]
        return field[1:].split(";", 1)[0] if field.startswith(("@", "<")) else ""
    if flag == "--data-urlencode":
        before = value.split("=", 1)[0]
        return before.split("@", 1)[1] if "@" in before else ""
    return ""


def _uploaded(name: str, args: list[str]) -> str | None:
    """The file a curl or wget command sends, if it sends one. `@-` is standard input, which this can't see."""
    if name not in _SENDS_FILE:
        return None
    return next((sent for flag, value in _options(args, _SHORT_WITH_VALUE[name]) for sent in [_file_sent(name, flag, value)] if sent and sent != "-"), None)


def _undeclared(name: str, args: list[str], folders: set[str]) -> tuple[str, list[str]]:
    """The installer, and the packages it names that no manifest here declares yet: the ones a guess could have invented."""
    try:
        from occam_commands import INSTALLERS
        from occam_evidence import installed_packages
        from occam_tools.manifests import normalize_dist, read_manifests

        name, args = _unwrapped(name, args)
        packages = [package for package in installed_packages(name, args, INSTALLERS) if package not in _TOOLING]
        declared: set[str] = set()
        for folder in folders if packages else ():
            found = read_manifests(Path(folder), [file for file in _MANIFESTS if os.path.isfile(os.path.join(folder, file))])
            declared |= {*found["python"], *found["node"], *found["rust"], *found["go"]}
    except Exception:  # occam: ignore[swallowed-exception] a note isn't worth failing a hook for
        return name, []
    return name, [package for package in packages if package not in declared and normalize_dist(package) not in declared]


def _install_note(name: str, packages: list[str]) -> str:
    registry = _REGISTRY.get(name)
    check = f"`occam deps --online --name {registry}:{packages[0]}`" if registry else "its registry page"
    return (f"This installs {', '.join(packages[:4])}, which nothing in this repository declares yet. If a name came from memory, confirm it's the real "
            f"package before relying on it, with {check}: a guessed name can belong to someone else's malware.")


MAX_STEPS_READ = 200  # notes that read each step's settings or compare it with documents stop here, since a command can hold thousands


def names_a_production_database(unquoted: str, settings: list[str] = ()) -> bool:
    pairs = _SETTING.findall(unquoted) + [tuple(setting.split("=", 1)) for setting in settings]
    return any(_DATABASE_NAME.search(name) and names_production(value) for name, value in pairs)


def reach_notes(name: str, args: list[str], tests_on_production: bool, folders: set[str]) -> Iterator[tuple[str, str]]:
    """Where a command reaches beyond this machine's work: production data, another account, another host, or a package registry. Without
    `folders`, the command moved somewhere this can't see, so its manifests aren't read."""
    if tests_on_production and _runs_tests(name, args):
        yield "tests-on-production", _TESTS_ON_PRODUCTION
    if name == "ssh" and _tests_on_a_production_host(args):
        yield "tests-on-production", _TESTS_ON_PRODUCTION
    live = _load_test_host(name, args)
    if live:
        yield "load-test-live", (f"This load test sends traffic to {live}, which doesn't name itself local, staging or test. If that's production, each virtual user "
                                 "places real orders, payments or sign-ups there. Point it at an isolated environment.")
    provenance = _install_source(name, args)
    if provenance:
        yield f"install-source:{provenance[0]}", provenance[1]
    sent = _uploaded(name, args)
    if sent:
        where = next((arg.split("/")[2] for arg in args if re.match(r"https?://[^/]", arg)), "another host")
        yield f"uploads-a-file:{sent}", f"This sends {sent} to {where}. Check that this destination is approved for this repository's code and data."
    installer, undeclared = _undeclared(name, args, folders) if folders else (name, [])
    if undeclared:
        yield f"undeclared-install:{undeclared[0]}", _install_note(installer, undeclared)


def _tests_on_a_production_host(args: list[str]) -> bool:
    """`ssh prod-web 'RAILS_ENV=production bundle exec rspec'`: tests run on a production host, or there with a production environment."""
    rest, value_next = list(args), False
    while rest:
        word = rest.pop(0)
        if value_next:
            value_next = False
        elif word.startswith("-"):
            value_next = word in _SSH_VALUE_OPTIONS
        else:
            host = word
            break
    else:
        return False
    remote = " ".join(rest)
    if not remote:
        return False
    try:
        from shell_reading import parse_shell

        steps = parse_shell(remote)[0][:MAX_STEPS_READ]
    except Exception:  # occam: ignore[swallowed-exception] a note isn't worth failing a hook for
        return False
    from occam_commands import head

    runs = any(_runs_tests(*head(words)) for words in steps)
    return runs and bool(names_production(host) or SERVER_ENVIRONMENT.search(remote) or names_a_production_database(remote))


def _load_test_host(name: str, args: list[str]) -> str | None:
    if name not in _LOAD_TESTERS or (_LOAD_TESTERS[name] and _LOAD_TESTERS[name] not in args[:2]):
        return None
    hosts = re.findall(r"https?://([^/\s'\"]+)", " ".join(args)[:20_000])
    return next((host for host in hosts if not _NOT_A_LIVE_HOST.search(host)), None)


def _install_source(name: str, args: list[str]) -> tuple[str, str] | None:
    """Installs from a source nobody vetted: pip's `--extra-index-url`, and a third-party Homebrew tap."""
    name, args = _unwrapped(name, args)
    if (name in ("pip", "pip3") or (name == "uv" and args[:1] == ["pip"])) and "install" in args[:2] and any(arg.startswith("--extra-index-url") for arg in args):
        return "extra-index", ("--extra-index-url lets that index and PyPI both offer each package, and pip takes the highest version from either, so a public "
                               "package with the same name can stand in for an internal one. Check its provenance: `--index-url` for the internal index, or the one pip.conf names.")
    if name == "brew" and args[:1] in (["tap"], ["install"]):
        tap = next((arg for arg in args[1:] if not arg.startswith("-") and arg.count("/") >= 1 and not arg.lower().startswith("homebrew/")), None)
        if tap:
            owner = "/".join(tap.split("/")[:2])
            return owner, (f"This installs from {owner}, a third-party Homebrew tap, whose formulas run as you and fetch what they like. Check the tap's "
                           "provenance, that it belongs to the project it's named after, before running what it installs.")
    return None


_SENDS_STANDARD_INPUT = re.compile(r"[@<]-|\s-T\s+-|\bhttps?[ \t]+(?:POST|PUT|PATCH)\b")
_DEFAULT_ENV_FILE = re.compile(r"(?:^|/)\.env(?:\.local|\.development(?:\.local)?)?$")
_STDIN_SENDERS = {"curl", "wget", "http", "https"}
_FILE_READERS = {"cat", "base64", "gzip", "bzip2", "xz", "zstd", "zip"}
_PUBLISHERS = {"twine": ("-r", "--repository", "--repository-url"), "poetry": ("-r", "--repository"), "flit": ("--repository",), "hatch": ("-r", "--repo"),
               "uv": ("--publish-url", "--index")}
_EXPLICIT = {"kubectl": ("--context", "--kubeconfig", "--cluster"), "helm": ("--kube-context", "--kubeconfig"), "helmfile": ("--kube-context",),
             "skaffold": ("--kube-context", "--kubeconfig"), "kapp": ("--kubeconfig-context", "--kubeconfig"), "gcloud": ("--project", "--account", "--configuration"),
             "az": ("--subscription",), "aws": ("--profile",), "firebase": ("--project", "-P"), "heroku": ("-a", "--app", "-r", "--remote"),
             "docker": ("--context", "-c", "-H", "--host"), "terraform": (), "doctl": ("--context",)}
# Tools that act on whatever cluster kubectl's current context names, so a kubectl switch is theirs too.
_KUBE_CONTEXT_READERS = {"helm", "helmfile", "skaffold", "kapp"}
_EXPLICIT_SETTINGS = {"kubectl": {"KUBECONFIG"}, "helm": {"KUBECONFIG", "HELM_KUBECONTEXT"}, "helmfile": {"KUBECONFIG"}, "skaffold": {"KUBECONFIG", "SKAFFOLD_KUBE_CONTEXT"},
                      "kapp": {"KUBECONFIG", "KAPP_KUBECONFIG_CONTEXT"},
                      "gcloud": {"CLOUDSDK_CORE_PROJECT", "CLOUDSDK_CORE_ACCOUNT", "CLOUDSDK_ACTIVE_CONFIG_NAME"},
                      "az": {"AZURE_SUBSCRIPTION_ID", "ARM_SUBSCRIPTION_ID"}, "aws": {"AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_ACCESS_KEY_ID"},
                      "firebase": {"FIREBASE_PROJECT", "GCLOUD_PROJECT"}, "heroku": {"HEROKU_APP"}, "docker": {"DOCKER_CONTEXT", "DOCKER_HOST"}, "terraform": {"TF_WORKSPACE"},
                      "doctl": {"DIGITALOCEAN_CONTEXT"}}
_KUBECTL_CHANGES = {"apply", "create", "delete", "patch", "replace", "scale", "set", "label", "annotate", "edit", "drain", "cordon", "uncordon", "taint", "run", "expose", "autoscale"}
_CLOUD_VERBS = {"create", "delete", "deploy", "update", "patch", "import", "set", "resize", "restart", "reset", "start", "stop", "apply", "restore", "rollback", "promote",
                "failover", "upload", "rm", "cp", "mv", "enable", "disable", "add", "remove", "assign", "purge", "scale", "swap", "up", "add-iam-policy-binding", "set-iam-policy"}
_AWS_CHANGES = re.compile(r"^(?:create|delete|put|update|modify|terminate|run|start|stop|reboot|restore|attach|detach|associate|disassociate|register|deregister|invoke|publish|send"
                          r"|import|deploy|tag|untag|set|enable|disable|cancel|copy|reset|rotate|purge|upload)(?:-|$)")
_HEROKU_CHANGES = {"config:set", "config:unset", "config:add", "config:remove", "ps:restart", "ps:scale", "ps:stop", "ps:type", "ps:resize", "restart", "pg:reset", "pg:promote",
                   "pg:backups:restore", "pg:killall", "run", "run:detached", "releases:rollback", "rollback", "maintenance:on", "maintenance:off", "addons:create", "addons:destroy",
                   "apps:destroy", "domains:add", "domains:remove", "features:enable", "features:disable", "labs:enable", "labs:disable", "access:add", "access:remove"}
_FIREBASE_CHANGES = re.compile(r"^(?:deploy|firestore:delete|database:(?:set|update|push|remove)|functions:delete|hosting:disable|auth:import|remoteconfig:rollback|ext:(?:install|uninstall|update))$")
_DOCKER_CHANGES = {"rm", "rmi", "stop", "kill", "restart", "run", "create", "start", "pause", "update"}
_DOCKER_PAIRS = {("compose", "down"), ("compose", "up"), ("compose", "rm"), ("compose", "stop"), ("compose", "restart"), ("compose", "kill"), ("compose", "run"), ("volume", "rm"),
                 ("volume", "prune"), ("system", "prune"), ("container", "rm"), ("container", "prune"), ("network", "rm"), ("image", "rm"), ("image", "prune")}


# A switch kept in a config file or folder the command names for itself changes nothing a later command reads.
_OWN_CONFIG_FLAGS = {"kubectl": ("--kubeconfig",), "gcloud": ("--configuration",), "docker": ("--config",), "doctl": ("--config", "-c")}
_OWN_CONFIG_SETTINGS = {"kubectl": {"KUBECONFIG"}, "gcloud": {"CLOUDSDK_CONFIG", "CLOUDSDK_ACTIVE_CONFIG_NAME"}, "az": {"AZURE_CONFIG_DIR"},
                        "aws": {"AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"}, "docker": {"DOCKER_CONFIG"}, "terraform": {"TF_DATA_DIR"}}


def switches(commands: list[list[str]]) -> list[tuple[str, str, str]]:
    """Commands that change which account, project or cluster a tool acts on from now on, as (tool, what it now points at, the command).
    Each is a step's words as written, since a `KUBECONFIG=...` before it keeps the switch out of what later commands read."""
    from occam_commands import head

    found = []
    for words in commands:
        name, args = head(words)
        switch = _switch(name, args)
        if not switch:
            continue
        tool, target = switch
        settings = {setting.split("=", 1)[0] for setting in settings_of(words)}
        if settings & _OWN_CONFIG_SETTINGS.get(tool, set()) or any(arg == flag or arg.startswith(flag + "=") for arg in args for flag in _OWN_CONFIG_FLAGS.get(tool, ())):
            continue
        found.append((tool, target, " ".join([name, *args])[:120]))
    return found


class _Switch(NamedTuple):
    """A command that changes which account, project or cluster a tool acts on from now on."""
    programs: tuple[str, ...]
    words: tuple[str, ...]  # what its words that aren't options start with
    tool: str  # whose target it changes
    target: tuple  # where the new target is: an index into those words, or groups of options read in turn, or None; then what to say when
    #                it isn't there, or None when the command switches nothing without it
    unless: frozenset = frozenset()  # words that mean it switches nothing
    unless_option: frozenset = frozenset()  # options, with or without a value, that mean the same: the credentials are written somewhere else


# Fetching a cluster's credentials also makes it kubectl's current context, unless they're written somewhere else or the context is left alone.
_SWITCHES = (
    _Switch(("gcloud",), ("container", "clusters", "get-credentials"), "kubectl", (3, None)),
    _Switch(("aws",), ("eks", "update-kubeconfig"), "kubectl", ((("--alias",), ("--name",)), "another cluster"), unless_option=frozenset({"--kubeconfig", "--dry-run"})),
    _Switch(("az",), ("aks", "get-credentials"), "kubectl", ((("--name", "-n"),), "another cluster"), unless_option=frozenset({"--file", "-f"})),
    _Switch(("doctl",), ("kubernetes", "cluster", "kubeconfig", "save"), "kubectl", (4, None), unless=frozenset({"--set-current-context=false"})),
    _Switch(("gcloud",), ("config", "set", "project"), "gcloud", (3, "another project")),
    _Switch(("gcloud",), ("config", "set", "account"), "gcloud", (3, "another project")),
    _Switch(("gcloud",), ("config", "configurations", "activate"), "gcloud", (3, "another project")),
    _Switch(("gcloud",), ("auth", "login"), "gcloud", (None, "a new login")),
    _Switch(("az",), ("account", "set"), "az", ((("--subscription", "-s", "--name", "-n"),), "another subscription")),
    _Switch(("az",), ("login",), "az", (None, "a new login")),
    _Switch(("aws",), ("configure", "set"), "aws", (None, "the settings it set")),
    _Switch(("aws",), ("sso", "login"), "aws", ((("--profile",),), "a new login")),
    _Switch(("firebase",), ("use",), "firebase", (1, None), unless=frozenset({"--add", "--clear", "--unalias"})),
    _Switch(("heroku",), ("git:remote",), "heroku", ((("-a", "--app"),), "another app")),
    _Switch(("docker",), ("context", "use"), "docker", (2, None)),
    _Switch(("terraform", "tofu"), ("workspace", "select"), "terraform", (2, None)),
    _Switch(("terraform", "tofu"), ("workspace", "new"), "terraform", (2, None)),
    _Switch(("doctl",), ("auth", "switch"), "doctl", ((("--context",),), "another context")),
)


def _switch(name: str, args: list[str]) -> tuple[str, str] | None:
    """The tool whose target this one command changes, and what to, or None."""
    plain = [arg for arg in args if not arg.startswith("-")]
    if name in ("kubectl", "kubectx", "kubens"):
        return _kubectl_switch(name, plain, args)
    for switch in _SWITCHES:
        if name in switch.programs and tuple(plain[:len(switch.words)]) == switch.words and not _stopped(switch, args):
            target = _switched_to(switch.target, plain, args)
            if target is not None:
                return switch.tool, target
    return None


def _kubectl_switch(name: str, plain: list[str], args: list[str]) -> tuple[str, str] | None:
    """kubectl's own context switches, which come after its options and their values, and kubectx's and kubens'. `kubectx -c` only prints
    the current one."""
    if name == "kubectl" and "use-context" in plain:
        return "kubectl", (plain[plain.index("use-context") + 1:] or ["another context"])[0]
    if name == "kubectl" and "set-context" in plain and "--current" not in args:
        return "kubectl", "the context it set"
    if name in ("kubectx", "kubens") and plain:
        return "kubectl", plain[0]
    return None


def _stopped(switch: _Switch, args: list[str]) -> bool:
    return bool(switch.unless & set(args)) or bool(switch.unless_option & {arg.split("=", 1)[0] for arg in args})


def _switched_to(target: tuple, plain: list[str], args: list[str]) -> str | None:
    where, otherwise = target
    if isinstance(where, int):
        return plain[where] if len(plain) > where else otherwise
    return next((value for flags in where or () for value in [option_value(args, flags)] if value), "") or otherwise


def _changes_through(name: str, args: list[str], settings: set[str]) -> str | None:
    """The tool whose remembered target this command changes something through, naming none of its own."""
    tool = "heroku" if name == "git" and args[:2] == ["push", "heroku"] else "terraform" if name == "tofu" else name
    if tool not in _EXPLICIT or _names_its_target(tool, args, settings) or _a_dry_run(args):
        return None
    lowered = [arg.lower() for arg in args]
    plain = [arg for arg in lowered if not arg.startswith("-")]
    changes = _CHANGES.get(tool, _uses_a_cloud_verb)(name, plain, lowered)
    return ("kubectl" if tool in _KUBE_CONTEXT_READERS else tool) if changes else None


def _a_dry_run(args: list[str]) -> bool:
    return any(arg in ("--dry-run", "--dryrun") or arg.startswith("--dry-run=") for arg in args)


def _names_its_target(tool: str, args: list[str], settings: set[str]) -> bool:
    return bool(settings & _EXPLICIT_SETTINGS[tool]) or any(arg == flag or arg.startswith(flag + "=") for arg in args for flag in _EXPLICIT[tool])


def _starts_with_one_of(words: set[str]) -> Callable[[str, list[str], list[str]], bool]:
    return lambda name, plain, lowered: bool(plain) and plain[0] in words


def _uses_a_cloud_verb(name: str, plain: list[str], lowered: list[str]) -> bool:
    return bool(set(plain) & _CLOUD_VERBS)


def _kubectl_changes(name: str, plain: list[str], lowered: list[str]) -> bool:
    sub = subcommand("kubectl", lowered) or ""
    return sub in _KUBECTL_CHANGES or (sub == "rollout" and bool(set(plain) & {"restart", "undo", "pause", "resume"}))


def _kapp_changes(name: str, plain: list[str], lowered: list[str]) -> bool:
    return plain[:1] in (["deploy"], ["delete"]) or plain[:2] in (["app-group", "deploy"], ["app-group", "delete"])


def _cloud_cli_changes(name: str, plain: list[str], lowered: list[str]) -> bool:
    """gcloud and az: a changing verb anywhere, outside their own configuration, login and help."""
    return plain[:1] not in (["config"], ["auth"], ["account"], ["login"], ["logout"], ["help"], ["info"], ["version"]) and _uses_a_cloud_verb(name, plain, lowered)


def _aws_changes(name: str, plain: list[str], lowered: list[str]) -> bool:
    copies = plain[:1] == ["s3"] and plain[1:2] in (["cp"], ["mv"], ["rm"], ["sync"], ["rb"], ["mb"])
    return plain[:1] != ["configure"] and (any(_AWS_CHANGES.match(arg) for arg in plain) or copies)


def _heroku_changes(name: str, plain: list[str], lowered: list[str]) -> bool:
    return name == "git" or (bool(plain[:1]) and plain[0] in _HEROKU_CHANGES)


def _docker_changes(name: str, plain: list[str], lowered: list[str]) -> bool:
    return bool((plain[:1] and plain[0] in _DOCKER_CHANGES) or tuple(plain[:2]) in _DOCKER_PAIRS)


def _terraform_changes(name: str, plain: list[str], lowered: list[str]) -> bool:
    """`apply PLANFILE` applies what was planned, where it was planned."""
    changes = plain[:1] in (["apply"], ["destroy"], ["import"], ["taint"], ["untaint"], ["force-unlock"]) and not (plain[:1] == ["apply"] and plain[1:])
    return changes or plain[:2] in (["state", "rm"], ["state", "mv"], ["state", "push"])


# How each tool's command changes something, from its name, its words that aren't options, and all its words lowered. Any other tool:
# a changing verb anywhere.
_CHANGES = {"kubectl": _kubectl_changes, "helm": _starts_with_one_of({"install", "upgrade", "uninstall", "rollback", "delete", "del", "un"}),
            "helmfile": _starts_with_one_of({"apply", "sync", "destroy", "delete"}), "skaffold": _starts_with_one_of({"run", "deploy", "dev", "delete", "apply"}),
            "kapp": _kapp_changes, "gcloud": _cloud_cli_changes, "az": _cloud_cli_changes, "aws": _aws_changes,
            "firebase": lambda name, plain, lowered: bool(plain[:1]) and bool(_FIREBASE_CHANGES.match(plain[0])), "heroku": _heroku_changes,
            "docker": _docker_changes, "terraform": _terraform_changes}


def where_it_lands(programs: list[tuple[str, list[str]]], commands: list[list[str]], command: str, switched: dict, cwd: str) -> Iterator[tuple[str, str]]:
    """Notes on where a command's effect lands, read step by step in order: a change made through a target switched to earlier, a
    production env file copied over the one tools read, and code sent or published somewhere."""
    here: dict[str, tuple[str, str]] = {}  # tools switched earlier in this same command: what to, and by which step
    added: dict[str, str] = {}  # remotes this command adds, by name
    for (name, args), words in zip(programs, commands):
        yield from _through_a_switched_target(name, args, words, switched, here)
        plain = [arg for arg in args if not arg.startswith("-")]
        yield from _env_file_switched(name, plain)
        yield from _pushes_elsewhere(name, plain, added)
        yield from _publishes(name, args, words, cwd)
    yield from _sent_from_stdin(command)


def _through_a_switched_target(name: str, args: list[str], words: list[str], switched: dict, here: dict) -> Iterator[tuple[str, str]]:
    """A change made through a target switched to in this command, or in an earlier one. Adds this step's own switch to `here` after."""
    tool = _changes_through(name, args, {setting.split("=", 1)[0] for setting in settings_of(words)}) if (switched or here) and (name in _EXPLICIT or name in ("git", "tofu")) else None
    if tool and tool in here:
        target, how = here[tool]
        yield f"switched-and-changed:{tool}:{target}", (f"This switches {tool} to {target} with `{how}` and then changes something through it in this same command. "
                                                        f"Confirm {target} is the one meant before this runs, or name it in the step that changes something.")
    elif tool and tool in switched:
        target, how = switched[tool]
        yield f"ambient-target:{tool}:{target}", (f"This acts on whichever account, project or cluster {tool} last switched to, and that's {target}: `{how}` switched it "
                                                  "earlier. Name the target in this command, or confirm it's the one meant, before this changes anything.")
    here.update((switched_tool, (target, how)) for switched_tool, target, how in switches([words]))


def _env_file_switched(name: str, plain: list[str]) -> Iterator[tuple[str, str]]:
    if name in ("cp", "mv", "ln", "install") and len(plain) >= 2 and _DEFAULT_ENV_FILE.search(plain[-1]) and any(PRODUCTION_ENV_FILE.search(" " + path) for path in plain[:-1]):
        yield "env-file-switch", (f"This puts {plain[0]} in {plain[-1]}, which tools here read by default, so later seeds, migrations and tests act on production's "
                                  "account, project or cluster and its database. Name the environment in each command instead, or put the file back before anything writes.")


def _pushes_elsewhere(name: str, plain: list[str], added: dict[str, str]) -> Iterator[tuple[str, str]]:
    """A push to a remote this command added, or to an address named only here. Adds this step's own new remote to `added`."""
    if name == "git" and plain[:2] in (["remote", "add"], ["remote", "set-url"]) and len(plain) > 3:
        added[plain[2]] = plain[3]
    elif name == "git" and plain[:1] == ["push"] and len(plain) > 1 and (plain[1] in added or re.match(r"^(?:https?://|git@|ssh://)", plain[1])):
        where = added.get(plain[1], plain[1])
        yield f"pushes-elsewhere:{where}", (f"This sends this repository's history to {where}, a remote {'this command just added' if plain[1] in added else 'named only here'}. "
                                            "Check that this destination is approved for this repository's code.")


def _publishes(name: str, args: list[str], words: list[str], cwd: str) -> Iterator[tuple[str, str]]:
    plain = [arg for arg in args if not arg.startswith("-")]
    for check in _PUBLISH_CHECKS:
        found = check(name, args, plain, words, cwd)
        if found:
            yield found


def _gist(name: str, args: list[str], plain: list[str], words: list[str], cwd: str) -> tuple[str, str] | None:
    if name != "gh" or plain[:2] != ["gist", "create"]:
        return None
    files = [arg for index, arg in enumerate(args[2:], 2) if not arg.startswith("-") and args[index - 1] not in ("-d", "--desc", "-f", "--filename", "-w")]
    public = "--public" in args or "-p" in args
    return "gist", (f"This sends {', '.join(files[:4]) or 'what it reads'} to a {'public ' if public else ''}GitHub gist, which anyone with the link can read. "
                    "Check that this destination is approved for this repository's code and data.")


def _sonar(name: str, args: list[str], plain: list[str], words: list[str], cwd: str) -> tuple[str, str] | None:
    host = next((arg.split("=", 1)[1] for arg in args if arg.startswith(("-Dsonar.host.url=", "--sonar.host.url=", "-Dsonar.host.url="))), "")
    host = host or next((word.split("=", 1)[1] for word in words if word.startswith("SONAR_HOST_URL=")), "")
    if not host:
        return None
    return f"sonar:{host}", (f"This sends the source to {host} for analysis, instead of the server this project's own configuration names. "
                             "Check that this destination is approved for this repository's code.")


def _public_pypi(name: str, args: list[str], plain: list[str], words: list[str], cwd: str) -> tuple[str, str] | None:
    flags = _PUBLISHERS.get(name)
    if not flags or plain[:1] not in (["upload"], ["publish"]) or any(arg == flag or arg.startswith(flag + "=") for arg in args for flag in flags):
        return None
    settings = {setting.split("=", 1)[0] for setting in settings_of(words)}
    if settings & {"TWINE_REPOSITORY", "TWINE_REPOSITORY_URL", "POETRY_REPOSITORIES", "UV_PUBLISH_URL"} or "--dry-run" in args:
        return None
    return "publishes-public", (f"This sends the package to {name}'s default repository, public PyPI, where anyone can install it. Check that's where this package "
                                "is meant to go; a named repository, as `-r internal`, picks another.")


def _public_npm(name: str, args: list[str], plain: list[str], words: list[str], cwd: str) -> tuple[str, str] | None:
    if name not in ("npm", "pnpm", "yarn") or plain[:1] != ["publish"] or "--dry-run" in args or any(arg.startswith("--registry") for arg in args) or not cwd:
        return None
    if _npm_registry(cwd) is not None:
        return None
    return "publishes-public", ("This sends the package to the public npm registry, where anyone can install it, since nothing here names another registry. "
                                "Check that's where this package is meant to go.")


_PUBLISH_CHECKS = (_gist, _sonar, _public_pypi, _public_npm)


MAX_NPMRC_READ = 16_000  # .npmrc is read only this far


def _npm_registry(cwd: str) -> str | None:
    """The registry package.json or .npmrc here names, "private" for a package npm won't publish, or None for the public default."""
    import json

    try:
        with open(os.path.join(cwd, "package.json"), encoding="utf-8") as handle:
            package = json.load(handle)
        if not isinstance(package, dict):
            return "unknown"
        if package.get("private") is True or (isinstance(package.get("publishConfig"), dict) and package["publishConfig"].get("registry")):
            return "private"
        scope = str(package.get("name") or "").split("/")[0] if str(package.get("name") or "").startswith("@") else ""
        npmrc = os.path.join(cwd, ".npmrc")
        if os.path.isfile(npmrc):
            with open(npmrc, encoding="utf-8", errors="replace") as handle:
                text = handle.read(MAX_NPMRC_READ)
            if re.search(r"^\s*registry\s*=", text, re.M) or (scope and f"{scope}:registry" in text):
                return "configured"
    except (OSError, ValueError):
        return "unknown"
    return None


def _sent_from_stdin(command: str) -> Iterator[tuple[str, str]]:
    """`jq --rawfile s src.ts ... | curl -d @- URL`: the file a pipeline reads, sent on through standard input."""
    if not _SENDS_STANDARD_INPUT.search(command):
        return
    try:
        from occam_commands import head
        from shell_reading import pipelines

        found = pipelines(command)[:MAX_STEPS_READ]
    except Exception:  # occam: ignore[swallowed-exception] a note isn't worth failing a hook for
        return
    for stages in found:
        read: list[str] = []
        for stage in stages[:MAX_STEPS_READ]:
            name, args = head(stage.words)
            if name in _STDIN_SENDERS and read and _sends_stdin(name, args):
                where = next((arg.split("/")[2] for arg in args if re.match(r"https?://[^/]", arg)), "another host")
                yield f"uploads-a-file:{read[0]}", f"This sends {', '.join(read[:3])} to {where}. Check that this destination is approved for this repository's code and data."
                break
            read += _files_read(name, args)


def _sends_stdin(name: str, args: list[str]) -> bool:
    if name not in _SENDS_FILE:
        return name in ("http", "https")
    for flag, value in _options(args, _SHORT_WITH_VALUE[name]):
        if value in ("@-", "<-") or (flag in _SENDS_FILE[name] and value == "-") or (flag in ("-F", "--form") and value.endswith(("=@-", "=<-"))):
            return True
    return False


def _files_read(name: str, args: list[str]) -> list[str]:
    if name in ("jq", "gojq"):
        return _jq_files(args)
    if name in _FILE_READERS:
        return [arg for arg in args if not arg.startswith("-")]
    if name == "tar" and args and "c" in args[0].lstrip("-"):
        return _tar_inputs(args)
    if name == "git" and args[:1] == ["archive"]:
        return ["the repository"]
    return []


def _jq_files(args: list[str]) -> list[str]:
    """The files jq reads: those after its program, and those `--rawfile` and `--slurpfile` read into a name."""
    found, index, program_seen = [], 0, False
    while index < len(args):
        if args[index] in ("--rawfile", "--slurpfile") and index + 2 < len(args):
            found.append(args[index + 2])
            index += 3
            continue
        if not args[index].startswith("-"):
            if program_seen:
                found.append(args[index])
            program_seen = True
        index += 1
    return found


def _tar_inputs(args: list[str]) -> list[str]:
    """What `tar c...` archives: its words that aren't options or the archive it writes to."""
    return [arg for index, arg in enumerate(args[1:], 1) if not arg.startswith("-") and not (args[index - 1] in ("-f", "--file") or args[index - 1].endswith("f"))] or ["the archive"]
