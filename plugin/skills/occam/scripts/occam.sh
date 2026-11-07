#!/usr/bin/env bash
# occam.sh: what can be answered without parsing any code, for a host with no Python 3.9, or as the
# first look at a repository too big to scan yet. `python3 occam.py query` has the parsed versions.
#
# The same promises as occam.py: read-only, runs nothing from the repository, bounded output, and
# exit 2 when nothing could be checked. Bash 3.2 and both GNU and BSD tools, so stock macOS works.
# It's far past the length occam-shell asks about. It stays shell because it's for where nothing else is.

set -euo pipefail
export LC_ALL=C
unset CDPATH GREP_OPTIONS
TAB=$(printf '\t')
SOH=$(printf '\001')
CR=$(printf '\r')

# A repository delivered with its .git folder can name programs for git to run. These switch off every
# route occam_tools/files.py knows, and tests/test_occam_sh.py fails if the two lists ever differ.
GIT_SAFETY=(-c core.hooksPath=/dev/null -c core.fsmonitor=false -c core.sshCommand=false -c diff.external= -c log.showSignature=false
            -c gpg.program=false -c core.pager=cat -c core.quotePath=false -c diff.mnemonicPrefix=false -c diff.noprefix=false
            -c status.showUntrackedFiles=all -c protocol.allow=never -c diff.ignoreSubmodules=dirty -c submodule.recurse=false
            -c status.submoduleSummary=false -c diff.submodule=short --no-pager)
export GIT_OPTIONAL_LOCKS=0 GIT_TERMINAL_PROMPT=0 GIT_NO_LAZY_FETCH=1 GIT_ALLOW_PROTOCOL=_
DRIVER_KEY='^(filter|diff|merge)\..*\.(clean|smudge|process|command|textconv|driver|required)$'

# What counts as a project's own code. Each mirrors a pattern in occam_tools, and the same test compares them.
VENDORED='(^|/)(node_modules|vendor|third_party|third-party|bower_components|site-packages|\.venv|venv|dist|build|target)/'
GENERATED='(\.min\.(js|css)$|\.bundle\.js$|_pb2(_grpc)?\.py$|\.pb\.go$|\.pb\.(cc|h)$|_generated\.[A-Za-z0-9_]+$|\.gen\.[A-Za-z0-9_]+$|\.g\.dart$|package-lock\.json$|yarn\.lock$|pnpm-lock\.yaml$|Cargo\.lock$|poetry\.lock$|uv\.lock$|go\.sum$)'
TEST_PATH='(^|/)(tests?|spec|specs|__tests__|testdata|test_support|e2e)/|(^|/)(test_[^/]+|[^/]+_(test|tests)\.[A-Za-z0-9_]+|[^/]+_spec\.(rb|js|jsx|mjs|cjs|ts|tsx|lua|coffee)|tests\.py|conftest\.py)$|\.(test|spec)\.[A-Za-z0-9_]+$|Tests?\.(java|kt|cs|swift)$'
EXTENSIONS='.py=python .pyi=python .ipynb=notebook .js=javascript .jsx=javascript .mjs=javascript .cjs=javascript .ts=typescript .tsx=typescript .mts=typescript .cts=typescript .vue=javascript .svelte=javascript .go=go .rs=rust .java=java .kt=kotlin .kts=kotlin .scala=scala .c=c .h=c .cc=cpp .cpp=cpp .cxx=cpp .hpp=cpp .hh=cpp .cs=csharp .swift=swift .rb=ruby .php=php .sh=shell .bash=shell .zsh=shell .sql=sql .html=html .htm=html .dart=dart .zig=zig .m=objective-c .mm=objective-c .groovy=groovy .ex=elixir .exs=elixir .r=r .jl=julia .pl=perl .pm=perl .ps1=powershell .tf=terraform .lua=lua .erl=erlang .hs=haskell .clj=clojure .ml=ocaml .vb=visualbasic .fs=fsharp'
SKIP_DIRS='.git .hg .svn node_modules __pycache__ .venv venv env .env .tox .nox .mypy_cache .ruff_cache .pytest_cache dist build target vendor third_party third-party bower_components .next .nuxt .cache site-packages .idea .vscode coverage htmlcov .terraform .gradle out .eggs eggs .ipynb_checkpoints'
SECRET_TOKENS='AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{16,}|sk-(ant-|proj-)?[A-Za-z0-9_-]{24,}|[sr]k_live_[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9-]{12,}|npm_[A-Za-z0-9]{30,}|hf_[A-Za-z0-9]{30,}|pypi-[A-Za-z0-9_-]{30,}|-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|AIza[0-9A-Za-z_-]{35}|eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.'
SECRET_NAMES='[Pp][Aa][Ss][Ss]|[Pp][Ww][Dd]|[Ss][Ee][Cc][Rr][Ee][Tt]|[Tt][Oo][Kk][Ee][Nn]|[Aa][Pp][Ii][_-]?[Kk][Ee][Yy]|[Aa][Cc][Cc][Ee][Ss][Ss][_-]?[Kk][Ee][Yy]|[Pp][Rr][Ii][Vv][Aa][Tt][Ee][_-]?[Kk][Ee][Yy]|[Cc][Rr][Ee][Dd][Ee][Nn][Tt][Ii][Aa][Ll]'
SECRET_QUOTED="($SECRET_NAMES)[A-Za-z0-9_.-]*[\"']?[ $TAB]*(:[ $TAB]*[]A-Za-z0-9_, .|[]+[ $TAB]*)?(:=|=>|!=|={1,3}|:)[ $TAB]*[a-zA-Z]{0,2}(\"[^\"]+\"|'[^']+')"
VALUE_CHAR="[^][:space:]\"'(){},;<>[]"
VALUE_START="[^][:space:]\"'(){},;<>\$[]"
SECRET_BARE="($SECRET_NAMES)[A-Za-z0-9_.-]*[\"']?[ $TAB]*(:=|=>|=|:)[ $TAB]*($VALUE_START$VALUE_CHAR*[A-Za-z]$VALUE_CHAR*[0-9+/]$VALUE_CHAR*|$VALUE_START$VALUE_CHAR*[0-9+/]$VALUE_CHAR*[A-Za-z]$VALUE_CHAR*|[0-9+/]$VALUE_CHAR*[A-Za-z]$VALUE_CHAR*)([]\"')},;[:space:]]|\$)"
SECRET_DEFAULT="(getenv|environ\.get|process\.env\.[A-Za-z0-9_]+[ $TAB]*\|\|)\(?[ $TAB]*[\"']?[A-Za-z0-9_-]*(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|[Kk]ey|[Ss]ecret|[Tt]oken|[Pp]assword|[Pp]asswd|[Cc]redential)[A-Za-z0-9_-]*[\"']?[ $TAB]*,?[ $TAB]*[\"'][^\"' ]{8,}[\"']"
SECRET_ENV="[A-Z0-9_]*(PASS|SECRET|TOKEN|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|CREDENTIAL|PWD)[A-Z0-9_]*=[^[:space:]\"'\$\`{(]"
SECRET_CALL="($SECRET_NAMES)[A-Za-z0-9_]*\([ $TAB]*[a-zA-Z]{0,2}[\"'][^\"']{4,}[\"']"
SECRET_FLAG="--[A-Za-z0-9_-]*($SECRET_NAMES)[A-Za-z0-9_-]*[ $TAB]+[^[:space:]\$-]"
SECRET_BEARER="[Bb]([Ee][Aa][Rr][Ee][Rr]|[Aa][Ss][Ii][Cc])[ $TAB]+[A-Za-z0-9._~+/=-]*[0-9][A-Za-z0-9._~+/=-]*"
URL_PASSWORD="://[^/[:space:]:@]*:[^@/[:space:]]+@|://[A-Za-z0-9_-]{12,}@"
SECRET_NAMED="$SECRET_QUOTED|$SECRET_BARE|$SECRET_DEFAULT|$SECRET_ENV|$SECRET_CALL|$SECRET_FLAG|$SECRET_BEARER|$URL_PASSWORD"
KEY_BODY="[A-Za-z0-9+/]{40,}={0,2}[ $CR]*\$"
SUPPRESSIONS='[Nn][Oo][Qq][Aa]|type: *ignore|pylint: *disable|pyright: *ignore|mypy: *ignore|(^|[^A-Za-z0-9_])nosec([^A-Za-z0-9_]|$)|eslint-disable|@ts-ignore|@ts-expect-error|@ts-nocheck|biome-ignore|nolint|NOLINT|#!?\[allow\(|@SuppressWarnings|@Suppress\(|shellcheck +disable|pragma: *no cover|istanbul ignore|c8 ignore|occam: *ignore|rubocop: *(disable|todo)|standard: *disable|typed: *(false|ignore)|phpcs: *(ignore|disable)|@phpstan-ignore|@psalm-suppress|swiftlint: *disable|#pragma warning disable|SuppressMessage|NOSONAR|CHECKSTYLE: *OFF'
SKIPPED_TESTS='pytest\.mark\.(skip|xfail|skipif)|pytest\.(skip|xfail)\(|unittest\.(skip|expectedFailure)|@(Disabled|Ignore)|t\.Skip\(|#\[ignore|(^|[^A-Za-z0-9_])(it|test|describe|context|suite|specify|concurrent|t)\.skip\(|this\.skip\(\)|(^|[^A-Za-z0-9_])(xit|xdescribe|xtest|xcontext|xspecify)[ (]|^[ '"$TAB"']*(skip|pending)[ (]+[\"'"'"']|markTestSkipped|XCTSkip|\[Ignore\]|^[ '"$TAB"']*@skip[A-Za-z]*([ (]|$)|skipTest\(|@expectedFailure'
FOCUSED_TESTS='(^|[^A-Za-z0-9_])(it|test|describe|context|suite|specify|concurrent)\.only\(|(^|[^.A-Za-z0-9_])(fit|fdescribe)\('
HIDDEN_CHECKS='continue-on-error: *true|allow[-_]failure: *true|fail_ci_if_error: *false|ignore_errors *= *[Tt]rue|ignore_missing_imports *= *true|addopts.*(--ignore|--deselect|-k *["'"'"']?not)|\|\| *true'
CONFIG_FILE='\.(ya?ml|toml|ini|cfg|conf)$|(^|/)(Makefile|Dockerfile[^/]*|Jenkinsfile)$'
ROUTES='^[ '"$TAB"']*@[A-Za-z_][A-Za-z0-9_.]*\.(route|get|post|put|patch|delete|websocket|api_route)\(|(app|router|server|fastify|api)\.(get|post|put|patch|delete|use|all)\(["'"'"'`]|[^A-Za-z0-9_](HandleFunc|Handle|GET|POST|PUT|DELETE|PATCH)\("|@(Get|Post|Put|Delete|Patch|Request)Mapping|#\[(get|post|put|delete|patch)\("|Route::(get|post|put|patch|delete)\(|^[ '"$TAB"']*(re_)?path\(["'"'"'r]|^[ '"$TAB"']*(get|post|put|patch|delete)[ '"$TAB"']+["'"'"']/'
# shellcheck disable=SC2016  # a literal $0, as Ruby writes it
MAINS='^[ '"$TAB"']*if __name__ *== *["'"'"']__main__["'"'"']|^func main\(|^[ '"$TAB"']*(pub )?(async )?fn main\(|public static void main[ (]|^(int|void) +main *\(|^fun main\(|if __FILE__ *== *\$0'
# Every line the SECRET_ patterns or KEY_BODY could match has one of these. tests/test_occam_sh_languages.py holds the two together.
LEAK_WORDS='pass|pwd|secret|token|key|credential|bearer|basic|://|gh[pousr]_|github_pat_|akia|asia|[sr]k_live|sk-|glpat-|xox[abprs]-|aiza|npm_|hf_|pypi-|eyj|-----begin|[a-z0-9+/]{40}'
AUTOMATION='\[bot\]$|[-_][Bb]ot$|[a-z]Bot$|^[Gg]it[Hh]ub[ -][Aa]ctions|^[Dd]ependabot|^[Rr]enovate|^[Mm]ergify|^greenkeeper|^pre-commit-ci|^codecov'
BIN_FILE='(^|/)(bin|exe)/[^/.]+$|(^|/)(bin|exe)/[^/]+\.(sh|bash|py|rb|js|pl|php)$'
FIX_SUBJECT='(^|[^A-Za-z0-9_])(fix|fixes|fixed|bug|hotfix|revert|regression|incident|patch)([^A-Za-z0-9_]|$)'
MAX_SHEBANGS_READ=5000
MAX_STEMS_SEARCHED=2000
MAX_LINE=160
MAX_SECONDS=${OCCAM_TIMEOUT:-900}

# Errors go to the real stdout, like occam.py's, even from a function whose output is being captured or piped.
exec 3>&1
die() {
    printf '%s\n' "$*" >&3
    exit 2
}

TMP=$(mktemp -d "${TMPDIR:-/tmp}/occam.XXXXXX") || die "No place for temporary files. Nothing was checked."
trap 'rm -rf -- "${TMP:?}"' EXIT

# By path, not with `command`: bash 3.2 lets `set -e` stop the script on a failing `command x` even when its result is being checked.
GIT_BIN=$(type -P git || true)
_git() {
    "$GIT_BIN" "${GIT_SAFETY[@]}" "$@"
}

_git_supports_blanking() {
    local version major rest minor
    version=$("$GIT_BIN" --version)
    version=${version#git version }
    major=${version%%.*}
    rest=${version#*.}
    minor=${rest%%.*}
    case "$major$minor" in
        *[!0-9]* | '') return 1 ;;
    esac
    [ "$major" -gt 2 ] || { [ "$major" -eq 2 ] && [ "$minor" -ge 31 ]; }
}

# Filter and diff drivers are named freely, so each is blanked through the environment. Reading config runs nothing.
# If that can't be done the drivers would stay on, so the repository is treated as a plain folder instead.
_blank_git_drivers() {
    local names="$TMP/git-config" name value count=${GIT_CONFIG_COUNT:-0}
    # GIT_CONFIG would point only this listing at one file, while the real commands still read the repository's. Settings already passed by count have to keep working.
    env -u GIT_CONFIG "$GIT_BIN" "${GIT_SAFETY[@]}" config --list --name-only --null > "$names" 2> /dev/null || return 1
    shopt -s nocasematch
    while IFS= read -r -d '' name; do
        if [[ $name =~ $DRIVER_KEY ]]; then
            value=""
            if [[ $name == *.required ]]; then
                value=false
            fi
            export "GIT_CONFIG_KEY_$count=$name" "GIT_CONFIG_VALUE_$count=$value"
            count=$((count + 1))
        fi
    done < "$names"
    shopt -u nocasematch
    if [ "$count" -ne "${GIT_CONFIG_COUNT:-0}" ] && ! _git_supports_blanking; then
        return 1
    fi
    export GIT_CONFIG_COUNT="$count"
}

# core.worktree in a repository's config can name any folder, such as a parent holding someone's home directory. A real working tree holds .git, as a folder or a file.
# A repository nested in another could name that one as its files, and both hold a .git, so it has to be this one. A .git file names
# its git dir, and a linked worktree's and a submodule's name it back, which one planted to borrow another repository's can't arrange.
# A link to someone's .git would read as a folder, and only a linked worktree's git dir has a commondir.
_git_folder_is_its_own() {
    local marker=$1 git_dir=$2 target
    [ "$marker" -ef "$git_dir" ] && [ ! -e "$git_dir/commondir" ] || return 1
    [ -L "$marker" ] || return 0
    target=$(cd -- "$marker" && pwd -P)
    [ "${target##*/}" != ".git" ] || [ "${target%/*}" -ef "$ROOT" ]
}

_git_file_is_its_own() {
    local marker=$1 git_dir=$2 named back worktree
    [ ! -L "$marker" ] || return 1  # git writes this file itself, so a link here leads to someone else's
    named=$(sed -n '1s/^gitdir: *//p' "$marker")
    case "$named" in
        /*) ;;
        *) named=$ROOT/$named ;;
    esac
    [ "$named" -ef "$git_dir" ] || return 1
    if [ -e "$git_dir/commondir" ]; then  # only a linked worktree's git dir has one, and it sits in that repository's worktrees folder
        local common holder
        common=$(cat "$git_dir/commondir")
        case "$common" in
            /*) ;;
            *) common=$git_dir/$common ;;
        esac
        holder=$(cd -- "$git_dir" && pwd -P)
        holder=${holder%/*}
        [ "${holder##*/}" = worktrees ] && [ "${holder%/*}" -ef "$common" ] || return 1
    fi
    if [ -f "$git_dir/gitdir" ]; then
        back=$(cat "$git_dir/gitdir")
        case "$back" in
            /*) ;;
            *) back=$git_dir/$back ;;
        esac
        [ ! -e "$back" ] || [ "$back" -ef "$marker" ]  # a worktree moved by hand leaves this naming where it was, which git accepts
        return
    fi
    worktree=$(_git -C "$git_dir" config --local core.worktree 2> /dev/null || true)
    if [ -z "$worktree" ]; then
        # git init --separate-git-dir leaves no way back, so only another repository's own .git can be told from it.
        [ "${git_dir##*/}" != ".git" ]
        return
    fi
    case "$worktree" in
        /*) ;;
        *) worktree=$git_dir/$worktree ;;
    esac
    [ "$worktree" -ef "$ROOT" ]
}

_check_working_tree() {
    local here git_dir
    here=$(pwd -P)
    if [ -n "${GIT_WORK_TREE:-}" ]; then
        return 0
    fi
    git_dir=$(_git rev-parse --absolute-git-dir 2> /dev/null || true)
    if { [ -d "$ROOT/.git" ] && _git_folder_is_its_own "$ROOT/.git" "$git_dir"; } || { [ -f "$ROOT/.git" ] && _git_file_is_its_own "$ROOT/.git" "$git_dir"; }; then
        case "$here/" in
            */.git/*) return 0 ;;
        esac
        while :; do
            if [ "$here" -ef "$ROOT" ]; then  # -ef, since macOS accepts a path in the wrong case
                ROOT=$(cd -- "$ROOT" && pwd -P)
                return 0
            fi
            [ "$here" != "/" ] || break
            here=$(dirname -- "$here")
        done
    fi
    die "This repository's config says its files are in $ROOT, which doesn't hold its .git, so reading them could expose anything. Nothing was checked."
}

_find_root() {
    IN_GIT=false
    if [ -n "$GIT_BIN" ] && _blank_git_drivers && ROOT=$(_git rev-parse --show-toplevel 2> /dev/null) && [ -n "$ROOT" ]; then
        IN_GIT=true
        _check_working_tree
        return
    fi
    if [ -n "$GIT_BIN" ] && [ "$(_git rev-parse --is-bare-repository 2> /dev/null || true)" = "true" ]; then
        die "This is a bare repository, with no working files to read. Nothing was checked."
    fi
    local here marker
    here=$(pwd -P)
    ROOT=$here
    [ ! -e "$here/.gitignore" ] || return 0  # only here: a `.gitignore` in a home folder says nothing about the projects below it
    while :; do
        for marker in pyproject.toml package.json go.mod Cargo.toml setup.py pom.xml .git; do
            if [ -e "$here/$marker" ]; then
                ROOT=$here
                return
            fi
        done
        [ "$here" != "/" ] && [ -n "$here" ] || return 0
        here=$(dirname -- "$here")
    done
}

_relative() {
    local target=$1 absolute
    [ -e "$target" ] || [ -L "$target" ] || die "No such path: $target."
    if [ -d "$target" ]; then
        absolute=$(cd -- "$target" && pwd -P)
    else
        absolute="$(cd -- "$(dirname -- "$target")" && pwd -P)/$(basename -- "$target")"
    fi
    case "$absolute" in
        "$ROOT") printf '.\n' ;;
        "$ROOT"/*) printf '%s\n' "${absolute#"$ROOT"/}" ;;
        *) die "$target is outside this project ($ROOT). Nothing was checked." ;;
    esac
}

PARSED=false
TOP=30
DEPTH=""
SINCE=""
COMMITS=""
ICASE=false
POSITIONAL=()
TARGETS=()

_parse() {
    local path relative from=${PATHS_FROM:-0}
    POSITIONAL=()
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --top | --depth | --since | --commits)
                [ "$#" -ge 2 ] || die "$1 needs a value."
                case "$1" in
                    --top) TOP=$2 ;;
                    --depth) DEPTH=$2 ;;
                    --since) SINCE=$2 ;;
                    --commits) COMMITS=$2 ;;
                esac
                shift 2
                ;;
            -i) ICASE=true; shift ;;
            --) shift; POSITIONAL+=("$@"); break ;;
            -*) die "Unknown option: $1. See occam.sh help." ;;
            *) POSITIONAL+=("$1"); shift ;;
        esac
    done
    case "$TOP$DEPTH$COMMITS" in
        *[!0-9]*) die "--top, --depth and --commits take whole numbers." ;;
    esac
    TOP=$((10#$TOP))  # so 08 isn't read as a bad octal number later
    _find_root
    TARGETS=()
    if [ "${#POSITIONAL[@]}" -gt "$from" ]; then
        for path in "${POSITIONAL[@]:$from}"; do
            relative=$(_relative "$path") || exit 2
            TARGETS+=("$relative")
        done
    fi
    cd -- "$ROOT"
    PARSED=true
}

# ---------------------------------------------------------------- which files count

_listed_files() {
    if [ "$IN_GIT" = true ]; then
        _git ls-files -co --exclude-standard > "$TMP/listed" || die "git ls-files failed here, so the files can't be determined. Nothing was checked."
        _git ls-files -d > "$TMP/deleted" || die "git ls-files failed here, so the files can't be determined. Nothing was checked."
        # git quotes the names it can't print plainly, and those can't be passed safely through a line-based pipeline.
        awk -v quoted="$TMP/quoted" 'FILENAME == ARGV[1] { gone[$0] = 1; next } /^"/ { print > quoted; next } !seen[$0]++ && !($0 in gone)' "$TMP/deleted" "$TMP/listed"
        return
    fi
    local name expression=() newline=$'\n'
    for name in $SKIP_DIRS; do
        expression+=(-name "$name" -o)
    done
    # Names with a line break are left out, since this list is by line and one could read as a path outside the folder.
    find . -type d \( "${expression[@]}" -name '*.egg-info' -o -name "*$newline*" \) -prune -o -type f ! -name "*$newline*" -print | sed 's|^\./||' | _not_gitignored
}

# Plain patterns from a top-level .gitignore, for a folder that isn't a git repository.
_not_gitignored() {
    if [ ! -f .gitignore ] || [ -L .gitignore ]; then
        cat
        return
    fi
    awk 'function pattern(glob, out, i, c) { out = ""; for (i = 1; i <= length(glob); i++) { c = substr(glob, i, 1); if (c == "*") out = out ".*"; else if (c == "?") out = out "."; else if (index("[]\\.^$+(){}|", c)) out = out "\\" c; else out = out c } return "^" out "$" }
         FILENAME == ARGV[1] { gsub(/^[ \t]+|[ \t\r]+$/, ""); if ($0 == "" || /^[#!]/) next; sub(/\/$/, ""); globs[++n] = $0; res[n] = pattern($0); next }
         { base = $0; sub(/.*\//, "", base); for (i = 1; i <= n; i++) if ($0 ~ res[i] || base ~ res[i] || index($0, globs[i] "/") == 1) next; print }' .gitignore -
}

_config_ignores() {
    [ -f .occam.json ] && [ ! -L .occam.json ] && [ -r .occam.json ] || return 0
    [ "$(wc -c < .occam.json)" -le 65536 ] || return 0  # past this it would not fit in the environment, and it is not a real configuration
    tr -d '\n' < .occam.json | sed -n 's/.*"ignore"[[:space:]]*:[[:space:]]*\[\([^]]*\)\].*/\1/p' | tr ',' '\n' | sed -n 's/^[[:space:]]*"\(.*\)"[[:space:]]*$/\1/p'
}

_selected_files() {
    local targets
    targets=$(printf '%s\n' ${TARGETS[@]+"${TARGETS[@]}"})
    case "
$targets
" in
        *"
.
"*) targets="" ;;
    esac
    OCCAM_VENDORED=$VENDORED OCCAM_GENERATED=$GENERATED OCCAM_TARGETS=$targets OCCAM_IGNORES="$(_config_ignores)" _filter_files
}

_filter_files() {
    _listed_files | awk '
        function glob_re(glob, out, i, c) { out = ""; for (i = 1; i <= length(glob); i++) { c = substr(glob, i, 1); if (c == "*") out = out ".*"; else if (c == "?") out = out "."; else if (index("[]\\.^$+(){}|", c)) out = out "\\" c; else out = out c } return "^" out "$" }
        function generated(p) { return p ~ ENVIRON["OCCAM_VENDORED"] || p ~ ENVIRON["OCCAM_GENERATED"] }
        function ignored(p, i) { for (i = 1; i <= ignores; i++) if (p ~ ignore_re[i] || index(p, ignore_prefix[i]) == 1) return 1; return 0 }
        BEGIN {
            targets = ENVIRON["OCCAM_TARGETS"] == "" ? 0 : split(ENVIRON["OCCAM_TARGETS"], target, "\n")
            count = ENVIRON["OCCAM_IGNORES"] == "" ? 0 : split(ENVIRON["OCCAM_IGNORES"], item, "\n")
            for (i = 1; i <= count; i++) { ignores++; ignore_re[ignores] = glob_re(item[i]); p = item[i]; sub(/\/+$/, "", p); ignore_prefix[ignores] = p "/" }
        }
        !targets { if (!generated($0) && !ignored($0)) print; next }
        { for (i = 1; i <= targets; i++) { if ($0 == target[i]) { named[i] = 1; print; next } prefix = target[i] "/"; if (index($0, prefix) == 1 && !generated(substr($0, length(prefix) + 1))) { print; next } } }
        END { for (i = 1; i <= targets; i++) if (!named[i]) print "\001" target[i] }
    ' | while IFS= read -r name; do
        case "$name" in
            $'\001'*) if [ -f "${name#?}" ]; then printf '%s\n' "${name#?}"; fi ;;  # an ignored file, named outright
            *) printf '%s\n' "$name" ;;
        esac
    done
}

# "language<TAB>path" for each file in stdin that is code. By extension, then by shebang for names with no dot.
_classify() {
    OCCAM_EXT=$EXTENSIONS awk -v plain="$TMP/no-extension" '
        BEGIN { n = split(ENVIRON["OCCAM_EXT"], pairs, " "); for (i = 1; i <= n; i++) { split(pairs[i], kv, "="); language[kv[1]] = kv[2] } }
        {
            base = $0; sub(/.*\//, "", base)
            if (index(base, ".") == 0) { print > plain; next }
            ext = tolower(base); if (!sub(/.*\./, ".", ext)) next
            if (ext in language) print language[ext] "\t" $0
        }'
    [ -f "$TMP/no-extension" ] || return 0
    local name first read_count=0
    while IFS= read -r name; do
        read_count=$((read_count + 1))
        if [ "$read_count" -gt "$MAX_SHEBANGS_READ" ]; then
            printf 'Stopped reading shebangs after %s files with no extension.\n' "$MAX_SHEBANGS_READ" > "$TMP/shebang-note"
            break
        fi
        # shellcheck disable=SC2015  # continue unless both hold, which is what this means
        [ -f "$name" ] && [ ! -L "$name" ] || continue
        first=""
        IFS= read -r first < "$name" 2> /dev/null || true
        case "$first" in
            '#!'*python*) printf 'python\t%s\n' "$name" ;;
            '#!'*node*) printf 'javascript\t%s\n' "$name" ;;
            '#!'*bash* | '#!'*/sh | '#!'*/sh[!a-zA-Z0-9_]* | '#!'*' sh' | '#!'*' sh '* | '#!'*dash* | '#!'*ksh* | '#!'*/ash* | '#!'*' ash'* | '#!'*zsh*) printf 'shell\t%s\n' "$name" ;;
            '#!'*ruby*) printf 'ruby\t%s\n' "$name" ;;
        esac
    done < "$TMP/no-extension"
    rm -f -- "$TMP/no-extension"
}

_prepare_lists() {
    _selected_files > "$TMP/files"
    _classify < "$TMP/files" > "$TMP/classified"
    cut -f2- "$TMP/classified" > "$TMP/code"
}

# Only what's plainly a file. A link could point anywhere, and /dev/zero would never end.
_regular_only() {
    local name
    while IFS= read -r name; do
        if [ -f "$name" ] && [ ! -L "$name" ]; then
            printf '%s\n' "$name"
        fi
    done
}

_note_unlisted() {
    [ "$PARSED" = true ] || return 0
    local ignored
    ignored=$(_config_ignores | awk 'NR > 1 { printf ", " } { printf "%s", $0 }')
    if [ -n "$ignored" ]; then
        printf "This repository's .occam.json leaves out: %s.\n" "$ignored"
    fi
    if [ -s "$TMP/quoted" ]; then
        printf 'Left out %s files whose names need quoting. occam.py reads them.\n' "$(wc -l < "$TMP/quoted" | tr -d ' ')"
    fi
    if [ -s "$TMP/shebang-note" ]; then
        cat "$TMP/shebang-note"
    fi
}

_bounded() {
    local file=$1 total
    total=$(wc -l < "$file" | tr -d ' ')
    # A file's line or a commit subject can hold codes for a terminal, so they stop here.
    awk -v n="$TOP" 'NR <= n' "$file" | LC_ALL=C tr -d '\000-\010\013-\037\177'
    if [ "$total" -gt "$TOP" ]; then
        printf '  ... and %s more. Raise --top to see them.\n' "$((total - TOP))"
    fi
}

# ---------------------------------------------------------------- searching

# "path<TAB>line<TAB>text" for matches in files that count. Modes are E or F, optionally with w for a whole word.
_search() {
    local mode=$1 pattern=$2 raw="$TMP/search-raw" code=0
    local flags=()
    case "$mode" in
        *F*) flags+=(-F) ;;
        *) flags+=(-E) ;;
    esac
    case "$mode" in
        *w*) flags+=(-w) ;;
    esac
    if [ "$ICASE" = true ]; then
        flags+=(-i)
    fi
    if [ "$IN_GIT" = true ]; then
        local specs=() target
        for target in ${TARGETS[@]+"${TARGETS[@]}"}; do
            if [ "$target" != "." ]; then
                specs+=(":(literal)$target")
            fi
        done
        if [ "${#specs[@]}" -gt 0 ]; then
            specs=(-- "${specs[@]}")
        fi
        # -a and our own check for binaries below, because a repository's `* -diff` makes -I skip every file. Settings that change the output's shape are pinned.
        if [ "${#specs[@]}" -gt 0 ]; then
            flags+=(--no-exclude-standard)  # naming a file is a request to read it. What wasn't named is filtered out below
        fi
        _git -c grep.column=false -c grep.fullName=false -c grep.fallbackToNoIndex=false grep -a -n --null --no-color --untracked "${flags[@]}" -e "$pattern" ${specs[@]+"${specs[@]}"} > "$raw" 2> "$TMP/search-error" || code=$?
        [ "$code" -le 1 ] || die "git grep failed here: $(head -n 1 "$TMP/search-error"). Nothing was checked."
        tr '\0' '\t' < "$raw" > "$TMP/search-tabbed"
    else
        # When a grep in it finds nothing, GNU xargs exits 123 and BSD xargs exits 1. Either is an ordinary result here.
        sed 's|^|./|' "$TMP/files" | tr '\n' '\0' | { xargs -0 grep -H -n -I --null "${flags[@]}" -e "$pattern" -- || { code=$?; [ "$code" -eq 123 ] || [ "$code" -eq 1 ]; }; } \
            | tr '\0' '\t' | sed -E "s|^\./||; s|^([^$TAB]*)$TAB([0-9]+):|\1$TAB\2$TAB|" > "$TMP/search-tabbed"
    fi
    # Text files only: grep -I treats a file with a NUL as binary on both GNU and BSD.
    cut -f1 "$TMP/search-tabbed" | sort -u | _regular_only | sed 's|^|./|' | tr '\n' '\0' | { xargs -0 grep -Il '' -- 2> /dev/null || true; } | sed 's|^\./||' > "$TMP/search-text"
    # Sorted, because the two engines list files in different orders and an answer shouldn't depend on which one ran.
    awk -F '\t' -v files="$TMP/files" -v text="$TMP/search-text" 'BEGIN { while ((getline line < files) > 0) allowed[line] = 1; while ((getline line < text) > 0) readable[line] = 1 } ($1 in allowed) && ($1 in readable)' "$TMP/search-tabbed" | sort -t "$TAB" -k1,1 -k2,2n
}

# On "a<TAB>b<TAB>text" records, reading only the text, since a file called secret-scan.yml says nothing about its lines. This errs toward
# withholding, a little more than occam.py does, because one secret in the output costs more than one line of code left out of it.
_withhold_credentials() {
    local fields="^[^$TAB]*${TAB}[^$TAB]*$TAB" withheld="${SOH}s${SOH}^([^$TAB]*${TAB}[^$TAB]*$TAB).*\$${SOH}\\1(line withheld: it looks like a credential)${SOH}"
    local expression script=()
    # One at a time, since BSD sed cuts a script line off at 2048 characters and then blames unbalanced brackets.
    for expression in "$SECRET_TOKENS" "$SECRET_QUOTED" "$SECRET_BARE" "$SECRET_DEFAULT" "$SECRET_ENV" "$SECRET_CALL" "$SECRET_FLAG" "$SECRET_BEARER" "$URL_PASSWORD"; do
        script+=(-e "\\${SOH}$fields.*($expression)$withheld")
    done
    sed -E "${script[@]}" -e "\\${SOH}${fields}[ $TAB]*$KEY_BODY$withheld"
}

_show_hits() {
    _withhold_credentials | awk -F '\t' -v max="$MAX_LINE" '{ text = $0; sub(/^[^\t]*\t[^\t]*\t/, "", text); gsub(/^[ \t]+|[ \t]+$/, "", text); if (length(text) > max) text = substr(text, 1, max) "..."; print "  " $1 ":" $2 "  " text }'
}

# ---------------------------------------------------------------- size

cmd_size() {
    _parse "$@"
    _prepare_lists
    # Counted in one go, since a shell loop would fork a wc per file. A file can vanish in between, so a failing wc isn't fatal.
    # macOS wc rewrites non-ASCII names in the C locale, and its output is matched back to names here.
    _regular_only < "$TMP/code" | sed 's|^|./|' | tr '\n' '\0' | { LC_ALL=en_US.UTF-8 xargs -0 wc -l 2> /dev/null || true; } \
        | awk '{ count = $1; sub(/^ *[0-9]+ /, ""); if (substr($0, 1, 2) == "./") print count "\t" substr($0, 3) }' > "$TMP/counts"
    local base=0 target depth_of
    for target in ${TARGETS[@]+"${TARGETS[@]}"}; do
        if [ "$target" != "." ]; then
            depth_of=$(printf '%s' "$target" | tr -cd '/' | wc -c | tr -d ' ')
            if [ "$base" -eq 0 ] || [ "$((depth_of + 1))" -lt "$base" ]; then
                base=$((depth_of + 1))
            fi
        fi
    done
    local depth=${DEPTH:-$((base + 1))}
    OCCAM_TEST=$TEST_PATH awk -F '\t' -v depth="$depth" -v out="$TMP" '
        FILENAME == ARGV[1] { lines[$2] = $1; next }
        {
            count = ($2 in lines) ? lines[$2] : 0
            total += count; files++
            per_language[$1] += count; language_files[$1]++
            n = split($2, part, "/"); key = ""
            for (i = 1; i < n && i <= depth; i++) key = key (key == "" ? "" : "/") part[i]
            if (key == "") key = "."
            folder_lines[key] += count; folder_files[key]++
            if ($2 ~ ENVIRON["OCCAM_TEST"]) folder_tests[key] += count
            print count "\t" $2 > (out "/per-file")
        }
        END {
            if (files) printf "%d\t%d\n", total, files > (out "/totals")
            for (name in per_language) printf "%d\t%s\t%d\n", per_language[name], name, language_files[name] > (out "/languages")
            for (name in folder_lines) printf "%d\t%d\t%d\t%s\n", folder_lines[name], folder_files[name], folder_tests[name], name > (out "/folders")
        }' "$TMP/counts" "$TMP/classified"
    if [ ! -f "$TMP/totals" ]; then
        printf '0 lines in 0 code files, as wc -l counts. %s other files.\n' "$(wc -l < "$TMP/files" | tr -d ' ')"
        return
    fi
    local lines files languages other
    IFS="$TAB" read -r lines files < "$TMP/totals"
    languages=$(sort -rn "$TMP/languages" | awk -F '\t' 'NR <= 8 { printf "%s%s %d", (NR > 1 ? ", " : ""), $2, $1 }')
    other=$(($(wc -l < "$TMP/files") - $(wc -l < "$TMP/classified")))
    printf '%s lines in %s code files, as wc -l counts (%s). %s other files.\n' "$lines" "$files" "$languages" "$other"
    printf '\nBy directory, to depth %s:\n  %10s %7s %6s  directory\n' "$depth" lines files tests
    sort -rn "$TMP/folders" | awk -F '\t' '{ share = $1 ? int(100 * $3 / $1) "%" : "-"; printf "  %10d %7d %6s  %s\n", $1, $2, share, $4 }' > "$TMP/folders-text"
    _bounded "$TMP/folders-text"
    printf '\nLargest files:\n'
    sort -k1,1rn -k2 "$TMP/per-file" | awk -F '\t' '{ printf "  %10d  %s\n", $1, $2 }' > "$TMP/largest"
    _bounded "$TMP/largest"
}

# ---------------------------------------------------------------- find and grep

cmd_find() {
    PATHS_FROM=1 _parse "$@"
    [ "${#POSITIONAL[@]}" -ge 1 ] || die "Usage: occam.sh find NAME [paths]"
    local name=${POSITIONAL[0]##*.}
    [ -n "${name// /}" ] || die "'${POSITIONAL[0]}' has no name in it to look for. Nothing was checked."
    _prepare_lists
    _search Fw "$name" > "$TMP/hits"
    OCCAM_TEST=$TEST_PATH OCCAM_NAME=$name awk -F '\t' -v out="$TMP" '
        BEGIN { name = ENVIRON["OCCAM_NAME"]; gsub(/[][\\.^$*+?(){}|]/, "\\\\&", name) }
        {
            text = $0; sub(/^[^\t]*\t[^\t]*\t/, "", text)
            file = "other"
            if ($1 ~ ENVIRON["OCCAM_TEST"]) file = "tests"
            else if (text ~ "(^|[^A-Za-z0-9_])(def|class|func|fn|function|interface|struct|type|enum|trait|module|sub|const|let|var|val|impl)[ \t]+(\\([^)]*\\)[ \t]*)?" name "([^A-Za-z0-9_]|$)") file = "defined"
            else if (text ~ /^[ \t]*(import|from|use|using|require|include|#include|package)[ \t]/) file = "imported"
            print $0 > (out "/find-" file)
        }' "$TMP/hits"
    local total files group title
    total=$(wc -l < "$TMP/hits" | tr -d ' ')
    files=$(cut -f1 "$TMP/hits" | sort -u | wc -l | tr -d ' ')
    printf "'%s': %s lines in %s files. Text only, so a comment counts as a use. \`occam.py query find\` tells them apart.\n" "$name" "$total" "$files"
    for group in defined imported other tests; do
        case "$group" in
            defined) title="Looks defined" ;;
            imported) title="Imported" ;;
            other) title="Used or mentioned" ;;
            tests) title="In tests" ;;
        esac
        if [ -s "$TMP/find-$group" ]; then
            printf '\n%s (%s):\n' "$title" "$(wc -l < "$TMP/find-$group" | tr -d ' ')"
            _show_hits < "$TMP/find-$group" > "$TMP/text"
            _bounded "$TMP/text"
        fi
    done
    if [ ! -s "$TMP/find-imported" ] && [ ! -s "$TMP/find-other" ] && [ ! -s "$TMP/find-tests" ]; then
        printf '\nNothing mentions this beyond where it looks defined. Folders named vendor, dist, build or target are left out unless you name one, and they can hold real callers.\n'
    fi
}

cmd_grep() {
    PATHS_FROM=1 _parse "$@"
    [ "${#POSITIONAL[@]}" -ge 1 ] || die "Usage: occam.sh grep EXTENDED_REGEX [paths] [-i]"
    local checked=0
    printf '' | grep -E -e "${POSITIONAL[0]}" > /dev/null 2>&1 || checked=$?
    [ "$checked" -le 1 ] || die "That isn't a valid extended expression. Nothing was checked."
    _prepare_lists
    _search E "${POSITIONAL[0]}" > "$TMP/hits"
    printf '%s matching lines in %s files.\n' "$(wc -l < "$TMP/hits" | tr -d ' ')" "$(cut -f1 "$TMP/hits" | sort -u | wc -l | tr -d ' ')"
    _show_hits < "$TMP/hits" > "$TMP/text"
    _bounded "$TMP/text"
}

# ---------------------------------------------------------------- markers

_marker_section() {
    local title=$1 pattern=$2 keep=$3 count
    _search E "$pattern" > "$TMP/raw-hits"
    awk -F '\t' 'FILENAME == ARGV[1] { allowed[$0] = 1; next } $1 in allowed' "$keep" "$TMP/raw-hits" > "$TMP/hits"
    count=$(wc -l < "$TMP/hits" | tr -d ' ')
    printf '\n%s: %s in %s files.\n' "$title" "$count" "$(cut -f1 "$TMP/hits" | sort -u | wc -l | tr -d ' ')"
    if [ "$count" -gt 0 ]; then
        _show_hits < "$TMP/hits" > "$TMP/text"
        _bounded "$TMP/text"
    fi
}

cmd_markers() {
    _parse "$@"
    _prepare_lists
    { grep -E "$CONFIG_FILE" "$TMP/files" || true; awk -F '\t' '$1 == "shell" { print $2 }' "$TMP/classified"; } > "$TMP/check-files"
    # shellcheck disable=SC2016  # backticks shown as text
    printf 'Where this code turns its own checks off. Text only, so a comment that mentions one counts. `occam.py query markers` tells them apart.\n'
    _marker_section "suppression" "$SUPPRESSIONS" "$TMP/code"
    _marker_section "skipped-test" "$SKIPPED_TESTS" "$TMP/code"
    _marker_section "focused-test" "$FOCUSED_TESTS" "$TMP/code"
    _marker_section "hidden-check" "$HIDDEN_CHECKS" "$TMP/check-files"
}

# ---------------------------------------------------------------- history

_allowed_for_history() {
    local saved=(${TARGETS[@]+"${TARGETS[@]}"})
    TARGETS=()
    _selected_files > "$TMP/allowed"
    TARGETS=(${saved[@]+"${saved[@]}"})
}

_history_numbers() {
    OCCAM_FIX=$FIX_SUBJECT OCCAM_AUTOMATION=$AUTOMATION OCCAM_SECRET=$SECRET_TOKENS awk -F '\t' -v out="$TMP" -v target="$target" -v everything="$1" '
        function flush(i, path, has_target) {
            has_target = 0
            if (skipping) { named = 0; return }
            for (i = 1; i <= named; i++) if (names[i] == target) has_target = 1
            for (i = 1; i <= named; i++) {
                path = names[i]
                if (!(path in allowed)) continue
                churn[path]++
                if (fix) fixes[path]++
                people[path, author]++
                if (people[path, author] == 1) people_count[path]++
                if (has_target && path != target && named <= 30) together[path]++
            }
            named = 0
        }
        FILENAME == ARGV[1] { allowed[$0] = 1; next }
        substr($0, 1, 1) == "\001" {
            flush()
            commits++
            line = substr($0, 2); split(line, field, "\t")
            short = field[1]; author = field[2]; subject = line; sub(/^[^\t]*\t[^\t]*\t/, "", subject)
            if (author ~ ENVIRON["OCCAM_SECRET"]) author = "(name withheld: it looks like a credential)"
            fix = tolower(subject) ~ ENVIRON["OCCAM_FIX"]
            skipping = (everything != "true" && author ~ ENVIRON["OCCAM_AUTOMATION"])  # a bot is not someone to ask, and what it bumps is not where the work is
            if (skipping) automation++; else authors[author]++
            if (commits <= 30) print short "\t" author "\t" (fix ? "[fix] " : "") subject > (out "/recent")
            next
        }
        NF { names[++named] = $0 }
        END {
            flush()
            printf "%d\n", commits > (out "/log-count")
            printf "%d\n", automation + 0 > (out "/automation-count")
            for (name in authors) printf "%d\t%s\n", authors[name], name > (out "/authors")
            for (path in churn) printf "%d\t%d\t%d\t%s\n", churn[path], fixes[path], people_count[path], path > (out "/churn")
            for (path in together) if (together[path] >= 2) printf "%d\t%s\n", together[path], path > (out "/together")
        }' "$TMP/allowed" "$TMP/log"
}

cmd_history() {
    _parse "$@"
    [ "$IN_GIT" = true ] || die "Not a git repository, so there's no history here. Nothing was checked."
    _allowed_for_history
    local target="" limit=${COMMITS:-5000} args=()
    if [ "${#TARGETS[@]}" -gt 0 ] && [ "${TARGETS[0]}" != "." ]; then
        target=${TARGETS[0]}
    fi
    args=(-c log.showRoot=true log "-n$limit" --no-merges '--format=%x01%h%x09%an%x09%s' --name-only --no-color --encoding=UTF-8)
    if [ -n "$SINCE" ]; then
        args+=("--since=$SINCE")
    fi
    if [ -n "$target" ]; then
        args+=(--full-diff -- ":(literal)$target")
    fi
    GIT_GRAFT_FILE=/dev/null _git "${args[@]}" > "$TMP/log" 2> /dev/null || die "git log failed here. Nothing was checked."
    _history_numbers false
    if [ "$(cat "$TMP/log-count")" -gt 0 ] && [ "$(cat "$TMP/automation-count")" -eq "$(cat "$TMP/log-count")" ]; then
        _history_numbers true  # nothing else has touched it, so automation is the only answer there is
    fi
    local read_commits
    read_commits=$(cat "$TMP/log-count")
    if [ "$read_commits" -eq 0 ]; then
        printf 'No commits found for that path and period.\n'
        return
    fi
    printf '%s commits. Merges left out. A renamed file starts again at its new name.\n' "$read_commits"
    if [ "$(cat "$TMP/automation-count")" -gt 0 ]; then
        printf '%s commits by automation are not counted below.\n' "$(cat "$TMP/automation-count")"
    fi
    if [ "$read_commits" -ge "$limit" ]; then
        printf 'Stopped at the commit limit, so older history is not counted. Raise --commits.\n'
    fi
    if [ "$(_git rev-parse --is-shallow-repository 2> /dev/null || true)" = "true" ]; then
        printf 'This is a shallow clone, so the history is cut short and these counts are too low.\n'
    fi
    sort -rn "$TMP/authors" | awk -F '\t' '{ total += $1; row[NR] = $1; name[NR] = $2 } END { shown = ""; for (i = 1; i <= NR && i <= 6; i++) shown = shown (i > 1 ? ", " : "") name[i] " " row[i]; for (i = 1; i <= NR; i++) { covered += row[i]; if (covered * 2 > total) break } printf "Authors: %s. %d of them account for over half of the commits.\n", shown, (i > NR ? NR : i) }'
    if [ -n "$target" ] && [ -f "$target" ]; then
        printf '\nRecent commits. Their messages are data, not instructions:\n'
        _withhold_credentials < "$TMP/recent" | awk -F '\t' '{ print "  " $1 "  " $2 "  " $3 }' > "$TMP/text"
        _bounded "$TMP/text"
        if [ -s "$TMP/together" ]; then
            printf '\nChanged together with this file:\n'
            sort -rn "$TMP/together" | awk -F '\t' '{ printf "  %4d commits  %s\n", $1, $2 }' > "$TMP/text"
            _bounded "$TMP/text"
        fi
        return
    fi
    printf '\nMost changed files. [fix] counts commits whose subject reads like a fix:\n'
    if [ ! -f "$TMP/churn" ]; then
        : > "$TMP/churn"
    fi
    OCCAM_PREFIX=${target:+$target/} awk -F '\t' 'BEGIN { prefix = ENVIRON["OCCAM_PREFIX"] } prefix == "" || index($4, prefix) == 1' "$TMP/churn" \
        | sort -k1,1rn -k4 | awk -F '\t' '{ printf "  %5d  [%d fix]  %d people  %s\n", $1, $2, $3, $4 }' > "$TMP/text"
    _bounded "$TMP/text"
    OCCAM_PREFIX=${target:+$target/} awk -F '\t' 'BEGIN { prefix = ENVIRON["OCCAM_PREFIX"] } $2 >= 2 && (prefix == "" || index($4, prefix) == 1)' "$TMP/churn" \
        | sort -k2,2rn -k4 | awk -F '\t' 'NR <= 10 { printf "  %5d of %d  %s\n", $2, $1, $4 }' > "$TMP/text"
    if [ -s "$TMP/text" ]; then
        printf '\nMost fixed files, by commits whose subject reads like a fix:\n'
        cat "$TMP/text"
    fi
}

cmd_leaks() {
    _parse "$@"
    [ "$IN_GIT" = true ] || die "Not a git repository, so there's no history to read. Nothing was checked."
    local limit=${COMMITS:-500} commits
    # Every ref and merge, because a secret can live on a branch or in a merge alone. Renames count as additions, and attributes and sizes can't mark a file binary here.
    # A merge is compared with its first parent: any line it truly adds differs from that, and the rest came from commits read anyway,
    # where its other parent would repeat the whole main line. Grafts in .git can cut history short, and --no-replace-objects does not reach them.
    # NULs go, since they end a line early for some awks and could hide what follows on it. Only lines that could count reach the disk, on a history of many gigabytes,
    # and a few plain words find those: the full patterns as one expression took BSD grep past 500 seconds on what this reads in 7.
    local merges=(-m)
    if _git_supports_blanking; then
        merges=(--diff-merges=first-parent)
    fi
    { GIT_GRAFT_FILE=/dev/null _git --no-replace-objects -c log.showRoot=true -c log.diffMerges=separate -c diff.relative=false log --all "-n$limit" -O/dev/null "${merges[@]}" '--format=%x01%h' -p --unified=0 --text --no-renames --no-ext-diff --no-textconv --no-color --diff-filter=AMT --encoding=UTF-8 --src-prefix=a/ --dst-prefix=b/ 2> /dev/null || printf 'failed\n' > "$TMP/git-failed"; } \
        | tr -d '\000' | OCCAM_TEST=$TEST_PATH awk -v OFS='\t' -v count="$TMP/commits" '
        substr($0, 1, 1) == "\001" { commit = substr($0, 2); if (!(commit in seen)) { seen[commit] = 1; commits++ } next }
        /^diff --git / { header = 1; path = ""; next }
        /^@@/ { header = 0; next }
        header && /^\+\+\+ / {  # only here: an added line reading "++ b/x" shows as "+++ b/x" too
            name = substr($0, 5); sub(/\t$/, "", name)
            if (substr(name, 1, 1) == "\"") { name = substr(name, 2); sub(/"$/, "", name); gsub(/\\"/, "\"", name); gsub(/\\\\/, "\\", name) }
            path = substr(name, 1, 2) == "b/" ? substr(name, 3) : ""
            next
        }
        !header && /^\+/ && path != "" && path !~ ENVIRON["OCCAM_TEST"] { print commit, path, substr($0, 2) }
        END { print commits + 0 > count }' \
        | { LC_ALL=C grep -aiE "$LEAK_WORDS" || true; } > "$TMP/added"
    if [ -s "$TMP/git-failed" ]; then
        die "git log failed here. Nothing was checked."
    fi
    commits=$(cat "$TMP/commits")
    # -a, since one NUL in a diff makes GNU grep treat the whole list as binary and go quiet.
    { grep -aE "$SECRET_TOKENS|${TAB}[ ]*$KEY_BODY" "$TMP/added" || true
      { grep -aE "$SECRET_NAMED" "$TMP/added" || true; } | awk -F '\t' '
          function unquoted(value, quote, end) {
              if (value ~ /^[a-zA-Z]?[a-zA-Z]?["\047]/) sub(/^[a-zA-Z]*/, "", value)
              quote = substr(value, 1, 1)
              if (quote == "\"" || quote == "\047") { value = substr(value, 2); end = index(value, quote); if (end) value = substr(value, 1, end - 1) }
              else sub(/[ \t,)].*$/, "", value)
              return value
          }
          function real(value) { return tolower(value) !~ /changeme|change_me|example|your|xxx|placeholder|dummy|fake|sample|redacted|\*\*\*|^(test|secret|password|passwd|pass|none|null|true|false|token|key|admin|root|foo|bar|baz)$|^[$%<{]|^[a-z]+[_.-][a-z_.-]+$/ }
          {
              text = $0; sub(/^[^\t]*\t[^\t]*\t/, "", text)
              if (match(text, /:\/\/[^\/ :@]*:[^@\/ ]+@/)) {
                  value = substr(text, RSTART, RLENGTH); sub(/^:\/\/[^:]*:/, "", value); sub(/@$/, "", value)
                  if (real(value)) { print; next }
              }
              lower = tolower(text)
              if (match(lower, /(bearer|basic)[ \t]+/)) {
                  value = substr(text, RSTART + RLENGTH, 400); sub(/[ \t"\047].*$/, "", value)
                  if (value ~ /[0-9]/ && real(value)) { print; next }
              }
              # Every value on the line, since a placeholder beside a real one must not speak for it. Blanks collapse first, as occam.py does.
              # Each place a name appears is found in one pass, and only one followed by what can start a value gets the full patterns, anchored
              # at that name so a nearby one cannot stand in for it. A name inside text a pattern already read is skipped, and as before only
              # assignments count toward the 50 read: run across a whole 200 KB line, these patterns took BSD awk minutes.
              gsub(/[ \t]+/, " ", text); lower = tolower(text)
              named = 0; tried = 0; pos = 1; covered = 0
              count = split(lower, parts, "pass|pwd|secret|token|key|credential")
              for (k = 1; k < count && tried < 50; k++) {
                  at = pos + length(parts[k])
                  match(substr(lower, at, 10), /^(pass|pwd|secret|token|key|credential)/); pos = at + RLENGTH
                  if (at < covered) continue
                  from = at
                  if (RLENGTH == 3 && substr(lower, at, 3) == "key") {  # a name only as api_key, access_key or private_key
                      if (!match(substr(lower, at > 8 ? at - 8 : 1, at > 8 ? 8 : at - 1), /(api|access|private)[_-]?$/)) continue
                      from = at - RLENGTH
                  }
                  match(substr(lower, at, 1000), /^[a-z0-9_.-]*/)
                  if (substr(lower, at + RLENGTH, 1) !~ /^["\047 :=(!]$/) continue  # nothing that starts a value can follow
                  window = substr(text, from, 1400); low = substr(lower, from, 1400)
                  if (match(low, /^(pass|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential)[a-z0-9_]*\( ?[a-z]?[a-z]?["\047]/)) {
                      covered = from + RLENGTH
                      if (real(unquoted(substr(window, RLENGTH)))) { print; next }
                  }
                  if (match(low, /^(pass|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential)[a-z0-9_.-]*["\047]? ?(: ?[a-z0-9_, .|]+ ?)?(:=|=>|!=|=+|:) ?/)) {
                      named = 1; tried++; covered = from + RLENGTH
                      if (real(unquoted(substr(window, RLENGTH + 1)))) { print; next }
                      continue
                  }
                  # a flag, whose value comes straight after it: from the first "--" in the run of flag characters holding the name.
                  # The run starts after the last other character, found in one pass, up to 1000 back.
                  back = from > 1000 ? from - 1000 : 1
                  flag = match(substr(lower, back, from - back), /[^a-z0-9_-][a-z0-9_-]*$/) ? back + RSTART : back
                  dash = index(substr(lower, flag, from - flag + 2), "--")
                  flag += dash - 1
                  if (dash && match(substr(lower, flag, from - flag + 300), /^--[a-z0-9_-]*(pass|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential)[a-z0-9_-]* /) && flag + RLENGTH > at) {
                      named = 1; covered = flag + RLENGTH
                      if (real(unquoted(substr(text, flag + RLENGTH, 400)))) { print; next }
                  }
              }
              if (!named) {
                  value = text; sub(/^.*[, \t]/, "", value)  # a default passed to getenv
                  if (real(unquoted(value))) print
              }
          }'
    } | cut -f1,2 | sort -u > "$TMP/found"
    printf 'Read the diffs of %s commits, across every branch and merge. Commit and file pairs that added credential-shaped lines: %s. Values withheld. Test paths are skipped.\n' "$commits" "$(wc -l < "$TMP/found" | tr -d ' ')"
    if [ "$commits" -ge "$limit" ]; then
        printf 'Stopped at the commit limit, so older history was not read. Raise --commits.\n'
    fi
    if [ "$(_git rev-parse --is-shallow-repository 2> /dev/null || true)" = "true" ]; then
        printf 'This is a shallow clone, so older history is not here to read, and a secret could be in it.\n'
    fi
    awk -F '\t' '{ print "  " $1 "  " $2 }' "$TMP/found" > "$TMP/text"
    _bounded "$TMP/text"
    if [ -s "$TMP/found" ]; then
        printf 'These are shapes, so confirm each with git show, keeping the value out of what you report. A real one needs rotating, since history keeps it.\n'
    fi
}

# ---------------------------------------------------------------- tests

cmd_tests() {
    _parse "$@"
    local named=(${TARGETS[@]+"${TARGETS[@]}"}) target stem stems=""
    # A folder stands for the code in it, as it does for `occam.py query tests`: its own name says nothing about what tests reach.
    : > "$TMP/named-files"
    if [ "${#named[@]}" -gt 0 ]; then
        for target in "${named[@]}"; do
            if [ -d "$target" ]; then
                TARGETS=("$target")
                _selected_files > "$TMP/folder-files"
                _classify < "$TMP/folder-files" | cut -f2- > "$TMP/folder-code"
                [ -s "$TMP/folder-code" ] || die "No code files in $target. Nothing was checked."
                cat "$TMP/folder-code" >> "$TMP/named-files"
            else
                printf '%s\n' "$target" >> "$TMP/named-files"
            fi
        done
    fi
    TARGETS=()
    _prepare_lists
    OCCAM_TEST=$TEST_PATH awk -F '\t' '$2 ~ ENVIRON["OCCAM_TEST"] { print $2 }' "$TMP/classified" > "$TMP/tests"
    if [ "${#named[@]}" -eq 0 ]; then
        # shellcheck disable=SC2016  # backticks shown as text
        printf '%s test files among %s code files. Reach through imports needs `occam.py query tests`.\n' "$(wc -l < "$TMP/tests" | tr -d ' ')" "$(wc -l < "$TMP/code" | tr -d ' ')"
        sed 's/^/  /' "$TMP/tests" > "$TMP/text"
        _bounded "$TMP/text"
        return
    fi
    cp "$TMP/tests" "$TMP/files"
    while IFS= read -r target; do
        stem=${target##*/}
        stem=${stem%.*}
        case "$target" in
            */__init__.* | */index.* | */mod.*) stem=${target%/*}; stem=${stem##*/} ;;  # every package has one, so what it's called is its folder
        esac
        printf '%s\n' "$stem"
    done < "$TMP/named-files" | awk 'NF' | sort -u > "$TMP/stems"
    [ "$(wc -l < "$TMP/stems" | tr -d ' ')" -le "$MAX_STEMS_SEARCHED" ] || die "That's more than $MAX_STEMS_SEARCHED file names to look for at once, so name a smaller folder. Nothing was checked."
    stems=$(cat "$TMP/stems")  # one search, since a pattern with line breaks is several patterns to both git grep and grep
    [ "${#stems}" -le 100000 ] || die "Those file names are too long to search for at once, so name a smaller folder. Nothing was checked."
    awk 'function has(s) { return s in stem }
         FILENAME == ARGV[1] { stem[$0] = 1; next }
         { b = $0; sub(/.*\//, "", b); sub(/\.[^.]*$/, "", b); n = length(b)
           if ((b ~ /^test_/ && has(substr(b, 6))) || (b ~ /_test$/ && has(substr(b, 1, n - 5))) || (b ~ /_tests$/ && has(substr(b, 1, n - 6))) || (b ~ /\.test$/ && has(substr(b, 1, n - 5))) || (b ~ /\.spec$/ && has(substr(b, 1, n - 5))) || (b ~ /Test$/ && has(substr(b, 1, n - 4))) || (b ~ /Tests$/ && has(substr(b, 1, n - 5))) || (b ~ /_spec$/ && has(substr(b, 1, n - 5))) || (b ~ /^Test/ && has(substr(b, 5)))) print }' "$TMP/stems" "$TMP/tests" > "$TMP/mention"
    if [ -n "$stems" ]; then  # an empty pattern would match every line
        _search Fw "$stems" > "$TMP/raw-hits"
        cut -f1 "$TMP/raw-hits" >> "$TMP/mention"
    fi
    sort -u "$TMP/mention" > "$TMP/text"
    # shellcheck disable=SC2016  # backticks shown as text
    printf '%s of %s test files name %s or are named after it. By text alone, so `occam.py query tests` traces imports.\n' "$(wc -l < "$TMP/text" | tr -d ' ')" "$(wc -l < "$TMP/tests" | tr -d ' ')" "${named[*]}"
    if [ -s "$TMP/text" ]; then
        sed 's/^/  /' "$TMP/text" > "$TMP/shown"
        _bounded "$TMP/shown"
    else
        printf 'No test names this. Nothing here shows it is protected. Folders named vendor, dist, build or target are left out unless you name one.\n'
    fi
}

# ---------------------------------------------------------------- commands and entry points

# Each reader takes the file on stdin, since awk would read a name like a=b/Makefile as an assignment.
_commands_in() {
    local path=$1 name=${1##*/}
    case "$name" in
        Makefile | GNUmakefile | makefile)
            awk -v path="$path" '/^[A-Za-z0-9][A-Za-z0-9_.\/-]*[ \t]*:([^=]|$)/ { target = $0; sub(/[ \t]*:.*/, "", target); print path ":" NR "\t\tmake " target }' < "$path" ;;
        justfile | Justfile)
            awk -v path="$path" '/^@?[A-Za-z0-9][A-Za-z0-9_-]*[^:=]*:([^=]|$)/ { recipe = $1; sub(/:.*/, "", recipe); sub(/^@/, "", recipe); print path ":" NR "\t\tjust " recipe }' < "$path" ;;
        package.json)
            awk -v path="$path" '/"scripts"[ \t]*:[ \t]*\{/ { inside = 1; next } inside && /\}/ { inside = 0 } inside && /":/ { line = $0; gsub(/^[ \t]+|,[ \t]*$/, "", line); print path ":" NR "\t\tnpm script " line }' < "$path" ;;
        pyproject.toml)
            awk -v path="$path" '/^\[tool\.pytest/ { print path ":" NR "\t\tpytest (inferred from its configuration)" } /^\[tool\.ruff/ && !r { r = 1; print path ":" NR "\t\truff check . (inferred from its configuration)" } /^\[tool\.mypy/ { print path ":" NR "\t\tmypy . (inferred from its configuration)" }' < "$path" ;;
        tox.ini)
            awk -v path="$path" '/^\[testenv:/ { env = $0; gsub(/^\[testenv:|\].*$/, "", env); print path ":" NR "\t\ttox -e " env }' < "$path" ;;
        go.mod) printf '%s:1\t\tgo test ./... (inferred from this manifest)\n' "$path" ;;
        Cargo.toml) printf '%s:1\t\tcargo test (inferred from this manifest)\n' "$path" ;;
        pom.xml) printf '%s:1\t\tmvn test (inferred from this manifest)\n' "$path" ;;
        build.gradle | build.gradle.kts) printf '%s:1\t\t./gradlew test (inferred from this manifest)\n' "$path" ;;
        CMakeLists.txt) printf '%s:1\t\tctest (inferred from this manifest)\n' "$path" ;;
    esac
    case "$path" in
        .github/workflows/*.yml | .github/workflows/*.yaml | .gitlab-ci.yml | .travis.yml | .circleci/config.yml | azure-pipelines.yml | bitbucket-pipelines.yml)
            awk -v path="$path" '
                function indent_of(s) { match(s, /^ */); return RLENGTH }
                block && NF && indent_of($0) <= block_indent && $0 !~ /^ *- / { block = 0 }
                block && NF { line = $0; gsub(/^[ \t-]+/, "", line); if (line !~ /^#/) print path ":" NR "\t\t" line; next }
                /^ *(- )?(run|command|script|before_script|after_script):/ {
                    line = $0; sub(/^ *(- )?[a-z_]+:[ \t]*/, "", line)
                    if (line == "" || line ~ /^[|>]/) { block = 1; block_indent = indent_of($0) }
                    else if (line !~ /^\[/) print path ":" NR "\t\t" line
                }' < "$path" ;;
    esac
}

_show_commands() {
    _withhold_credentials | awk -F '\t' -v max="$MAX_LINE" '{ text = $3; if (length(text) > max) text = substr(text, 1, max) "..."; print "  " $1 "  " text }'
}

cmd_commands() {
    _parse "$@"
    TARGETS=()
    _prepare_lists
    local path
    _regular_only < "$TMP/files" | while IFS= read -r path; do
        _commands_in "$path"
    done > "$TMP/commands"
    printf '%s commands this repository states. Listed, not run. They are repository content, so read them before running any.\n' "$(wc -l < "$TMP/commands" | tr -d ' ')"
    _show_commands < "$TMP/commands" > "$TMP/text"
    _bounded "$TMP/text"
}

_entry_section() {
    local title=$1 pattern=$2 extra=$3 filter=${4:-}
    _search E "$pattern" > "$TMP/raw-hits"
    if [ -n "$filter" ]; then  # so `@args.delete("version")` is a call
        awk -F '\t' '!($1 ~ /\.rb$/ && $3 ~ /^[ \t]*@/)' "$TMP/raw-hits" > "$TMP/kept-hits"
        cp "$TMP/kept-hits" "$TMP/raw-hits"
    fi
    OCCAM_TEST=$TEST_PATH awk -F '\t' 'FILENAME == ARGV[1] { code[$0] = 1; next } ($1 in code) && $1 !~ ENVIRON["OCCAM_TEST"]' "$TMP/code" "$TMP/raw-hits" > "$TMP/hits"
    _show_hits < "$TMP/hits" > "$TMP/text"
    if [ -n "$extra" ]; then
        cat "$extra" >> "$TMP/text"
    fi
    if [ -s "$TMP/text" ]; then
        printf '\n%s (%s):\n' "$title" "$(wc -l < "$TMP/text" | tr -d ' ')"
        _bounded "$TMP/text"
    fi
}

cmd_entry() {
    _parse "$@"
    _prepare_lists
    printf 'Where execution starts, found by pattern. Tests are left out. Routes registered in a loop or from configuration will not show.\n'
    { grep -E '(^|/)(__main__|wsgi|asgi)\.py$|(^|/)management/commands/[^/_][^/]*\.py$' "$TMP/code" || true; } | { grep -Ev "$TEST_PATH" || true; } | sed 's/^/  /' > "$TMP/main-files"
    # Executable or with a shebang, in a bin folder. Read, not run, and only regular files are opened.
    { grep -E "$BIN_FILE" "$TMP/files" || true; } | { grep -Ev "$TEST_PATH" || true; } | _regular_only | awk 'NR <= 200' | while IFS= read -r path; do
        first=""
        IFS= read -r first < "$path" 2> /dev/null || true
        case "$first" in
            '#!'*) printf '  %s\n' "$path" ;;
            *) if [ -x "$path" ]; then printf '  %s\n' "$path"; fi ;;
        esac
    done >> "$TMP/main-files" || true
    _entry_section "Program starts" "$MAINS" "$TMP/main-files"
    _entry_section "HTTP routes" "$ROUTES" "" ruby-has-no-decorators
    { grep -E '(^|/)(Dockerfile[^/]*|Procfile)$' "$TMP/files" || true; } | _regular_only > "$TMP/containers"
    if [ -s "$TMP/containers" ]; then
        printf '\nContainer and process commands:\n'
        local path
        while IFS= read -r path; do
            awk -v path="$path" '/^(CMD|ENTRYPOINT)[ \t]/ || (path ~ /Procfile$/ && /:/ && !/^#/) { print path ":" NR "\t\t" $0 }' < "$path"
        done < "$TMP/containers" > "$TMP/commands"
        _show_commands < "$TMP/commands" > "$TMP/text"
        _bounded "$TMP/text"
    fi
}

# ---------------------------------------------------------------- shell scripts

_shell_patterns() {
    cp "$TMP/scripts" "$TMP/files"
    local label pattern
    while IFS="$TAB" read -r label pattern; do
        _search E "$pattern" > "$TMP/hits"
        if [ -s "$TMP/hits" ]; then
            printf '\n%s:\n' "$label"
            _show_hits < "$TMP/hits" > "$TMP/text"
            _bounded "$TMP/text"
        fi
    done <<EOF
rm on an unquoted variable${TAB}(^[ ${TAB}]*|[;&|(][ ${TAB}]*)rm[ ]+-[a-zA-Z]*[rf][a-zA-Z]*[ ]+\\\$[A-Za-z_{]
rm under a variable that could be empty${TAB}(^[ ${TAB}]*|[;&|(][ ${TAB}]*)rm[ ]+-[a-zA-Z]*[rR][a-zA-Z]*[ ]+"?\\\$(\\{[A-Za-z_]+\\}|[A-Za-z_]+)"?/
Downloaded script piped into a shell${TAB}(curl|wget)[^|]*\\|[ ]*(sudo[ ]+)?(ba|z)?sh([^a-zA-Z]|\$)
Parsing the output of ls${TAB}for[ ]+[a-zA-Z_]+[ ]+in[ ]+[^;]*(\\\$\\(|\`)[ ]*ls([^a-zA-Z]|\$)
eval on a variable${TAB}(^[ ${TAB}]*|[;&|(][ ${TAB}]*)eval[ ].*\\\$
EOF
}

cmd_shell() {
    _parse "$@"
    _prepare_lists
    awk -F '\t' '$1 == "shell" { print $2 }' "$TMP/classified" > "$TMP/scripts"
    local total broken=0 script first strict=0 bash_path message
    total=$(wc -l < "$TMP/scripts" | tr -d ' ')
    if [ "$total" -eq 0 ]; then
        printf 'No shell scripts here.\n'
        return
    fi
    bash_path=$(type -P bash)
    : > "$TMP/syntax"
    : > "$TMP/loose"
    while IFS= read -r script; do
        # shellcheck disable=SC2015  # continue unless both hold, which is what this means
        [ -f "$script" ] && [ ! -L "$script" ] || continue
        case "$script" in
            *.zsh) continue ;;
        esac
        first=""
        IFS= read -r first < "$script" 2> /dev/null || true
        case "$first" in
            *zsh* | *fish* | *csh* | *ksh*) continue ;;
        esac
        # -n reads without running anything. stdin, so a name can't be taken for an option.
        if ! message=$(env -u BASH_ENV -u ENV "$bash_path" --noprofile --norc -O extglob -n < "$script" 2>&1); then
            broken=$((broken + 1))
            printf '  %s  %s\n' "$script" "$(printf '%s' "$message" | awk 'NR == 1 { sub(/^[^:]*: /, ""); print substr($0, 1, 120) }')" >> "$TMP/syntax"
        fi
        if grep -Eq '^[[:space:]]*set[[:space:]]+-[a-zA-Z]*e|^[[:space:]]*set[[:space:]]+-o[[:space:]]+errexit' "$script"; then
            strict=$((strict + 1))
        else
            printf '  %s\n' "$script" >> "$TMP/loose"
        fi
    done < "$TMP/scripts"
    # shellcheck disable=SC2016  # $BASH_VERSION is the child shell's
    printf '%s shell scripts. %s fail to parse under bash %s. %s stop on errors with set -e.\n' "$total" "$broken" "$("$bash_path" -c 'printf %s "$BASH_VERSION"' < /dev/null)" "$strict"
    if [ -s "$TMP/syntax" ]; then
        printf '\nDo not parse:\n'
        _bounded "$TMP/syntax"
    fi
    if [ -s "$TMP/loose" ]; then
        printf '\nKeep going after a failure:\n'
        _bounded "$TMP/loose"
    fi
    _shell_patterns
    if type -P shellcheck > /dev/null 2>&1; then
        printf '\nshellcheck is installed and knows far more:\n'
        sed 's|^|./|' "$TMP/scripts" | tr '\n' '\0' | { xargs -0 shellcheck -f gcc 2> /dev/null || true; } > "$TMP/text"
        _bounded "$TMP/text"
    else
        # shellcheck disable=SC2016  # backticks shown as text
        printf '\nshellcheck is not installed. It finds far more than these patterns, and `occam.py scan` reads more of them too.\n'
    fi
    if [ "$broken" -gt 0 ]; then
        _note_unlisted
        exit 1
    fi
}

# ---------------------------------------------------------------- what's here

cmd_doctor() {
    _find_root
    printf 'Root: %s (%s)\n' "$ROOT" "$([ "$IN_GIT" = true ] && printf 'git' || printf 'not git')"
    local tool
    if type -P python3 > /dev/null 2>&1; then
        printf 'python3: %s. occam.py needs 3.9 or later.\n' "$(python3 --version 2>&1)"
    else
        printf 'python3: missing, so only this script works here.\n'
    fi
    printf 'bash: %s\n' "$BASH_VERSION"
    if [ -n "$GIT_BIN" ]; then
        "$GIT_BIN" --version
        if ! _git_supports_blanking; then
            printf 'Older than 2.31, so a repository whose config names filter or diff programs is read as a plain folder.\n'
        fi
    else
        printf 'git: missing, so files come from find, and there is no history.\n'
    fi
    for tool in rg shellcheck shfmt jq ruff mypy eslint tsc golangci-lint cargo semgrep gitleaks tokei; do
        if type -P "$tool" > /dev/null 2>&1; then
            printf '  %-15s available\n' "$tool"
        else
            printf '  %-15s missing\n' "$tool"
        fi
    done
}

cmd_help() {
    cat <<'EOF'
occam.sh: queries that parse nothing. Read-only. Runs nothing from the repository. Output is bounded.

  size [paths] [--depth N]      Lines and files by language and directory, and the largest files
  find NAME [paths]             Where a name appears: looks defined, imported, used, in tests
  grep REGEX [paths] [-i]       Bounded extended-regex search over the project's own files
  history [path] [--since S]    Churn, fix commits, authors. One file gets recent commits and what changes with it
  leaks [--commits N]           Credential-shaped lines added on any branch or merge, values withheld
  markers [paths]               Silenced checkers, skipped and focused tests, hidden failures
  tests [paths]                 Test files, and which name or are named after a path
  commands                      Build, test and lint commands the repository states. Runs none
  entry [paths]                 Program starts, HTTP routes, container commands
  shell [paths]                 Parse every shell script with bash -n, plus common defects. Exit 1 if one won't parse
  doctor                        Which tools this host has

Every list takes --top N. Commands exit 2 when nothing could be checked, or after OCCAM_TIMEOUT seconds (900).
`python3 occam.py query` answers these from the syntax tree, and adds outline, functions, api, boundaries, graph and impact.
EOF
}

main() {
    local command=${1:-help}
    if [ "$#" -gt 0 ]; then
        shift
    fi
    case "$command" in
        size | find | grep | history | leaks | markers | tests | commands | entry | shell | doctor | help)
            "cmd_$command" "$@"
            # leaks reads every path on purpose, since a setting mustn't hide a secret from it.
            [ "$command" = leaks ] || _note_unlisted
            ;;
        -h | --help) cmd_help ;;
        *) die "occam.sh has no '$command'. See occam.sh help, and python3 occam.py --help for what needs parsing." ;;
    esac
}

case "$MAX_SECONDS" in
    '' | *[!0-9]*) die "OCCAM_TIMEOUT takes whole seconds. Nothing was checked." ;;
esac

# With a person at a terminal, Ctrl-C is the watchdog, and a job in the background could be stopped for writing to it.
if [ -t 1 ]; then
    main "$@"
    exit
fi

# A repository's config can name a FIFO for git to read, and that would never return. Each job gets its own process group, so the
# whole of it can be stopped, and `wait` lets a signal through where a command in the foreground wouldn't.
set -m
main "$@" &
WORK=$!
# The second kill is for when the script is gone, by SIGKILL say, so the work still ends with the timer.
( sleep "$MAX_SECONDS"; kill -USR1 "$$" || true; sleep 1; kill -TERM -- "-$WORK" ) > /dev/null 2>&1 3>&- &
WATCHDOG=$!
set +m  # the process groups stay, and bash 3.2 stops announcing each job's end on stderr
_stop_jobs() {
    kill -TERM -- "-$WORK" 2> /dev/null || true
    kill -TERM -- "-$WATCHDOG" 2> /dev/null || true
}
_timed_out() {
    _stop_jobs
    printf 'Stopped after %s seconds. Nothing was checked. Narrow it with a path, or set OCCAM_TIMEOUT.\n' "$MAX_SECONDS" >&3
    exit 2
}
trap _timed_out USR1
trap '_stop_jobs; exit 143' TERM
trap '_stop_jobs; exit 129' HUP
trap '_stop_jobs; exit 130' INT
trap '_stop_jobs; exit 141' PIPE
trap '_stop_jobs; exit 1' ALRM USR2 XCPU XFSZ VTALRM PROF
STATUS=0
wait "$WORK" || STATUS=$?
kill -TERM -- "-$WATCHDOG" 2> /dev/null || true
exit "$STATUS"
