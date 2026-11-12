"""Every rule in the catalog has a case that must fire and a near miss that must not."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "skills" / "occam" / "scripts"))

from occam_tools import rules_js, rules_py, scan  # noqa: E402
from occam_tools.source import load  # noqa: E402
from occam_tools.catalog import BY_ID, CATEGORIES, LAYERS, RULES, SEVERITIES  # noqa: E402
from rule_cases_large import LARGE_CODEBASE_CASES  # noqa: E402
from rule_cases_quality import QUALITY_CASES  # noqa: E402
from rule_cases_resources import CONFIG_CASES, RESOURCE_CASES, SECRET_CASES  # noqa: E402
from rule_cases_js import JS_CASES  # noqa: E402
from rule_cases_jvmgo import JVMGO_CASES  # noqa: E402  team jvmgo
from rule_cases_native import NATIVE_CASES  # noqa: E402  team native
from rule_cases_config import CONFIG_TEAM_CASES  # noqa: E402  config team
from rule_cases_py import PY_CASES  # noqa: E402

# One file: (rule, path, code that should fire, near miss that shouldn't, or None if none is meaningful)
ONE_FILE = [
    # Incomplete
    ("stub-body", "app/billing.py", "def charge(card):\n    pass\n", "def charge(card):\n    return card.pay()\n"),
    ("stub-body", "app/billing.py", "def charge(card):\n    ...\n", "class Base:\n    def charge(self):\n        pass\n"),
    ("stub-raise", "app/billing.py", "def charge(card):\n    raise NotImplementedError\n", "from abc import ABC, abstractmethod\nclass P(ABC):\n    @abstractmethod\n    def charge(self):\n        raise NotImplementedError\n"),
    ("stub-raise", "src/a.ts", "function pay() { throw new Error('Not implemented'); }\n", "function pay() { throw new Error('Card declined'); }\n"),
    ("stub-raise", "src/a.rs", "fn pay() { todo!() }\n", "fn pay() { println!(\"todo\"); }\n"),
    ("stub-raise", "a.go", "func Pay() { panic(\"not implemented\") }\n", "func Pay() { panic(\"bad state\") }\n"),
    ("stub-body", "a.go", "func Pay() {\n}\n", "func Pay(x interface{}) interface{} {\n\treturn x\n}\n"),
    ("stub-raise", "A.kt", "fun pay() { TODO(\"later\") }\n", "fun pay() { println(\"TODO\") }\n"),
    ("truncation-marker", "app/a.py", "def f():\n    x = 1\n    # ... rest of the code\n", "def f():\n    # the rest of the code handles retries\n    return 1\n"),
    ("truncation-marker", "src/a.js", "function f() {\n  // ... existing code ...\n}\n", "function f() {\n  // existing code paths stay valid here for callers\n  return 1;\n}\n"),
    ("truncation-marker", "app/a.py", "# omitted for brevity\nx = 1\n", "# brevity matters in logs\nx = 1\n"),
    ("placeholder-comment", "app/a.py", "# TODO: implement real validation\nx = 1\n", "# TODO(sam): remove after 2027 once v1 clients are gone\nx = 1\n"),
    ("placeholder-comment", "app/a.py", "# In a real application this would call Stripe\nx = 1\n", "# Stripe calls this when a charge settles\nx = 1\n"),
    ("fake-success", "app/auth.py", "def verify_token(token):\n    return True\n", "def verify_token(token):\n    return token == load()\n"),
    ("fake-success", "src/auth.ts", "function verifyToken(t) { return true; }\n", "function verifyToken(t) { return check(t); }\n"),
    ("fake-data", "app/a.py", "RESULT = MOCK_USERS\n", "RESULT = users\n"),
    # Defending against what can't happen
    ("useless-except", "app/a.py", "def f():\n    try:\n        return g()\n    except ValueError:\n        raise\n", "def f():\n    try:\n        return g()\n    except KeyError:\n        raise\n    except ValueError:\n        return 0\n"),
    ("useless-except", "app/a.py", "def f():\n    try:\n        return g()\n    except ValueError as e:\n        raise e\n", "def f():\n    try:\n        return g()\n    except ValueError as e:\n        raise TypeError('x') from e\n"),
    ("useless-except", "app/a.py", "def f():\n    try:\n        return g()\n    except ValueError:\n        raise\n", "def f():\n    try:\n        return g()\n    except ValueError:\n        log()\n        raise\n"),
    ("useless-except", "src/a.js", "function f() { try { g(); } catch (e) { throw e; } }\n", "function f() { try { g(); } catch (e) { log(e); throw e; } }\n"),
    ("useless-except", "src/a.ts", "function f() { try { g(); } catch (e) { throw e } }\n", "function f() { try { g(); } catch (e) { throw wrap(e); } }\n"),
    ("ts-double-cast", "src/a.ts", "const u = data as unknown as User;\n", "const u = data as User;\n"),
    ("ts-double-cast", "src/a.ts", "const u = data as any as User;\n", "const s = 'data as unknown as User';\n"),
    # Security
    ("hardcoded-secret", "app/a.py", 'API_KEY = "abc123def456ghi789"\n', 'API_KEY = os.environ["API_KEY"]\n'),
    ("hardcoded-secret", "src/a.js", 'const k = "AKIA' + 'IOSFODNN7ABCDEFG";\n', 'const k = process.env.KEY;\n'),  # AWS's documented EXAMPLE key isn't a credential
    ("hardcoded-secret", "app/a.py", 'password = "hunter2hunter2"\n', 'password = "changeme"\n'),
    ("sql-injection", "app/a.py", 'def f(c, n):\n    c.execute(f"SELECT * FROM t WHERE n = {n}")\n', 'def f(c, n):\n    c.execute("SELECT * FROM t WHERE n = ?", (n,))\n'),
    ("sql-injection", "app/a.py", 'def f(c, n):\n    c.execute("SELECT * FROM t WHERE n = " + n)\n', 'def f(c, ids):\n    marks = ",".join("?" * len(ids))\n    c.execute(f"SELECT * FROM t WHERE n IN ({marks})", ids)\n'),
    ("sql-injection", "src/a.js", "db.query(`SELECT * FROM t WHERE id = ${id}`);\n", "db.query('SELECT * FROM t WHERE id = $1', [id]);\n"),
    ("sql-injection", "a.go", 'db.Query(fmt.Sprintf("SELECT * FROM t WHERE id = %d", id))\n', 'db.Query("SELECT * FROM t WHERE id = ?", id)\n'),
    ("shell-injection", "app/a.py", "import subprocess\ndef f(n):\n    subprocess.run(f'ls {n}', shell=True)\n", "import subprocess\ndef f(n):\n    subprocess.run(['ls', n])\n"),
    ("shell-injection", "app/a.py", "import os\ndef f(n):\n    os.system('ls ' + n)\n", "import os\ndef f():\n    os.system('ls')\n"),
    ("shell-injection", "src/a.js", "execSync(`ls ${dir}`);\n", "execFileSync('ls', [dir]);\n"),
    ("shell-injection", "a.c", "void f(char *c) { system(c); }\n", "void f(char *c) { my_system_call(c); }\n"),
    ("dynamic-eval", "app/a.py", "def f(x):\n    return eval(x)\n", "def f():\n    return eval('1+1')\n"),
    ("dynamic-eval", "src/a.js", "eval(x);\n", "retrieval(x);\n"),
    ("unsafe-deserialize", "app/a.py", "import pickle\ndef f(b):\n    return pickle.loads(b)\n", "import json\ndef f(b):\n    return json.loads(b)\n"),
    ("unsafe-deserialize", "app/a.py", "import yaml\ndef f(b):\n    return yaml.load(b)\n", "import yaml\ndef f(b):\n    return yaml.load(b, Loader=yaml.SafeLoader)\n"),
    ("tls-disabled", "app/a.py", "import requests\nrequests.get(u, verify=False, timeout=3)\n", "import requests\nrequests.get(u, verify=True, timeout=3)\n"),
    ("tls-disabled", "src/a.js", "new Agent({ rejectUnauthorized: false });\n", "new Agent({ rejectUnauthorized: true });\n"),
    # self-review: a ternary's other arm, and reading the variable, don't turn checking off
    ("tls-disabled", "src/a.js", "const o = { ...opts, rejectUnauthorized: false };\n", "const strictSsl = secure ? !!options.rejectUnauthorized : false;\n"),
    ("tls-disabled", "src/a.js", "process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';\n", "if (process.env.NODE_TLS_REJECT_UNAUTHORIZED !== '0') { warn(); }\n"),
    ("tls-disabled", "run.sh", "#!/bin/sh\nNODE_TLS_REJECT_UNAUTHORIZED=0 node app.js\n", "#!/bin/sh\n[ \"$NODE_TLS_REJECT_UNAUTHORIZED\" = 0 ] && echo unsafe\n"),
    ("tls-disabled", "src/a.js", "spawn('node', ['x'], { env: { NODE_TLS_REJECT_UNAUTHORIZED: '0' } });\n", "const off = process.env.NODE_TLS_REJECT_UNAUTHORIZED === '0';\n"),
    # review of the self-review fixes: ??= still turns it off, and a bare variable or the environment read in a ternary doesn't
    ("tls-disabled", "src/a.js", "process.env.NODE_TLS_REJECT_UNAUTHORIZED ??= '0';\n", "const strictSsl = secure ? !!rejectUnauthorized : false;\n"),
    ("tls-disabled", "src/a.js", "const agent = new Agent({\n  rejectUnauthorized: false,\n});\n", "const v = cond ? process.env.NODE_TLS_REJECT_UNAUTHORIZED : '1';\n"),
    # second review: a ternary with two spaces after ?
    ("tls-disabled", "src/a.js", "https.request({ host, rejectUnauthorized: false });\n", "const strictSsl = secure ?  rejectUnauthorized : false;\n"),
    # self-review: an OpenAPI model's type map names types, not credentials
    ("hardcoded-secret", "k8s/models/v1_volume.py", "class C:\n    client_secret = 'Q7v2pLx9Rk4m'\n", "class V1Volume:\n    openapi_types = {\n        'secret_ref': 'V1SecretReference',\n        'api_keys': 'list[str]',\n        'client_secret': 'V1Secret',\n    }\n"),
    # review of the self-review fixes: a CamelCase password with digits is still one, and a versioned type named for anything is a type
    ("hardcoded-secret", "app/settings.py", "DB_PASSWORD = 'Admin123Password'\n", "openapi_types = {\n    'secret_ref': 'V1LocalObjectReference',\n    'password_ref': 'V1beta1SecretKeySelector',\n}\n"),
    ("jwt-unverified", "app/a.py", 'jwt.decode(t, options={"verify_signature": False})\n', 'jwt.decode(t, key, algorithms=["RS256"])\n'),
    ("fail-open", "app/auth.py", "def verify_token(t):\n    try:\n        return check(t)\n    except Exception:\n        return True\n", "def verify_token(t):\n    try:\n        return check(t)\n    except Exception:\n        return False\n"),
    ("disabled-control", "app/a.py", "CSRF_ENABLED = False\nAUTH_REQUIRED = False\n", "AUTH_REQUIRED = True\n"),
    ("weak-crypto", "app/a.py", "import hashlib\ndef etag(b):\n    return hashlib.md5(b)\n", "import hashlib\ndef etag(b):\n    return hashlib.sha256(b)\n"),
    ("weak-password-hash", "app/a.py", "import hashlib\ndef hash_password(p):\n    return hashlib.md5(p)\n", "import hashlib\ndef etag(p):\n    return hashlib.md5(p, usedforsecurity=False)\n"),
    ("insecure-random", "app/a.py", "import random\ntoken = random.randint(0, 10)\n", "import random\nroll = random.randint(0, 10)\n"),
    ("insecure-random", "src/a.js", "const token = Math.random().toString(36);\n", "const jitter = Math.random() * 10;\n"),
    ("homemade-crypto", "app/a.py", "import base64\ndef encrypt(s):\n    return base64.b64encode(s)\n", "import base64\ndef encode(s):\n    return base64.b64encode(s)\n"),
    ("secret-compare", "app/a.py", "def f(signature, expected):\n    return signature == expected\n", "def f(name, expected):\n    return name == expected\n"),
    ("secret-compare", "app/a.py", "def f(signature, expected):\n    return signature == expected\n", "def f(artifact_digest, expected_digest):\n    return artifact_digest != expected_digest\n"),
    ("secret-compare", "app/a.py", "def f(req, webhook_secret):\n    return req.key == webhook_secret\n", "def f(self, style_signature):\n    return self._cached_theme_signature == style_signature\n"),
    ("secret-compare", "app/a.py", "def f(req, webhook_secret):\n    return req.key == webhook_secret\n", "def f(vault_secrets, row):\n    return vault_secrets.c.id == row['id']\n"),
    ("permissive-cors", "app/a.py", 'ALLOWED_HOSTS = ["*"]\n', 'ALLOWED_HOSTS = ["example.org"]\n'),
    ("debug-exposed", "app/a.py", "app.run(debug=True)\n", "app.run(debug=False)\n"),
    ("path-traversal", "app/a.py", "def f():\n    return open(request.args['p'])\n", "def f():\n    return open(SAFE_PATH)\n"),
    ("ssrf", "app/a.py", "def f():\n    return requests.get(request.args['u'], timeout=3)\n", "def f():\n    return requests.get(CONFIG_URL, timeout=3)\n"),
    ("xss-sink", "src/a.js", "el.innerHTML = name;\n", "el.textContent = name;\n"),
    ("xss-sink", "src/a.js", "el.innerHTML = '<b>' + name;\n", "el.innerHTML = '';\nel.innerHTML = \"<b>loading</b>\";\n"),
    ("unsafe-c-string", "a.c", "void f(char *d, char *s) { strcpy(d, s); }\n", "void f(char *d, char *s) { strncpy(d, s, 3); }\n"),
    ("insecure-tempfile", "app/a.py", "import tempfile\np = tempfile.mktemp()\n", "import tempfile\np = tempfile.mkstemp()\n"),
    ("world-writable", "deploy.sh", "#!/bin/sh\nset -e\nchmod 777 /srv\n", "#!/bin/sh\nset -e\nchmod 750 /srv\n"),
    ("curl-pipe-shell", "deploy.sh", "#!/bin/sh\nset -e\ncurl https://x.dev/i.sh | sh\n", "#!/bin/sh\nset -e\ncurl -o i.sh https://x.dev/i.sh\n"),
    ("hardcoded-secret", "app/a.py", 'import os\nKEY = os.getenv("PAY_API_KEY", "pb_live_9f8e7d6c5b4a")\n', 'import os\nKEY = os.getenv("PAY_API_KEY", "")\n'),
    ("hardcoded-secret", "app/a.py", 'DB = "postgres://admin:s3cr3tpw@db.internal/prod"\n', 'DB = "postgres://db.internal/prod"\n'),
    ("redos-regex", "app/a.py", "import re\nP = re.compile(r'^([a-z]+)+@x$')\n", "import re\nP = re.compile(r'^[a-z]+@x$')\n"),
    # self-review: each pass opens with a separator the repeat inside can't match, so there's one way to split
    ("redos-regex", "app/a.py", "import re\nP = re.compile(r'^\\w+(-[\\w-]+)*$')\n", "import re\nP = re.compile(r'^\\d+(?:[-:]\\d+)*$')\n"),
    ("redos-regex", "app/a.py", "import re\nP = re.compile(r'^(?:\\.?\\w+)*$')\n", "import re\nP = re.compile(r'^\\w+(\\.\\w+)*$')\n"),
    # review of the self-review fixes: an alternative inside can match what the separator opens
    ("redos-regex", "app/a.py", "import re\nP = re.compile(r'^(?:-\\d+|\\d+)*$')\n", "import re\nP = re.compile(r'^\\d+(?:-\\d+)*$')\n"),
    # second review: an escaped or bracketed | is a separator, not an alternative
    ("redos-regex", "app/a.py", "import re\nP = re.compile(r'^(?:,|\\w+)*$')\n", "import re\nP = re.compile(r'^\\w+(?:\\|\\w+)*(?:[|]\\d+)*$')\n"),
    ("env-flag-truthy", "app/a.py", "import os\nDEBUG = bool(os.getenv('D'))\n", "import os\nDEBUG = os.getenv('D') == '1'\n"),
    ("path-traversal", "app/a.py", "import os\n@app.get('/d')\ndef d(request):\n    name = request.query.get('file')\n    return open(os.path.join(ROOT, name))\n", "import os\n@app.get('/d')\ndef d(request):\n    return open(os.path.join(ROOT, 'fixed.csv'))\n"),
    # Error masking
    ("swallowed-exception", "app/a.py", "try:\n    f()\nexcept Exception as e:\n    logger.debug(e)\n", "try:\n    f()\nexcept Exception as e:\n    logger.error(e)\n    raise\n"),
    ("swallowed-exception", "app/a.py", "try:\n    f()\nexcept Exception:\n    pass\n", "try:\n    f()\nexcept KeyError:\n    pass\n"),
    ("swallowed-exception", "src/a.ts", "try { f(); } catch (e) {}\n", "try { f(); } catch (e) { log(e); }\n"),
    ("swallowed-exception", "src/a.ts", "try { f(); } catch {}\n", "try { f(); } catch { /* one holder's trouble is not the rename's */ }\n"),
    ("swallowed-exception", "src/a.js", "p.catch(() => {});\n", "p.catch((e) => log(e));\n"),
    ("bare-except", "app/a.py", "try:\n    f()\nexcept:\n    raise\n", "try:\n    f()\nexcept ValueError:\n    raise\n"),
    ("broad-wrap", "app/a.py", "def f():\n    try:\n        return g()\n    except Exception as e:\n        log(e)\n", "def f():\n    try:\n        return g()\n    except Exception as e:\n        log(e)\n        raise\n"),
    ("ignored-error", "a.go", "v, _ := strconv.Atoi(s)\n", "v, err := strconv.Atoi(s)\n"),
    ("ignored-error", "a.sh", "#!/bin/sh\nset -e\nrm x || true\n", "#!/bin/sh\nset -e\nrm x\n"),
    ("panic-in-library", "src/lib.rs", "fn f() { g().unwrap(); }\n", "fn f() -> R { g()?; Ok(()) }\n"),
    ("assert-validation", "app/a.py", "def pay(amount):\n    assert amount > 0\n    return amount\n", "def _pay(amount):\n    assert amount > 0\n    return amount\n"),
    ("suppression-comment", "app/a.py", "x = f()  # type: ignore\n", "x = f()  # type: ignore[arg-type]  # upstream stub is wrong\n"),
    ("suppression-comment", "src/a.ts", "// @ts-ignore\nconst x = 1;\n", "// a comment about types\nconst x = 1;\n"),
    # Tests
    ("test-no-assert", "tests/test_a.py", "def test_pay():\n    pay(1)\n", "def test_pay():\n    assert pay(1) == 1\n"),
    ("test-no-assert", "tests/test_a.py", "def test_pay():\n    async def scenario():\n        await pay(1)\n    asyncio.run(scenario())\n",
     "def test_pay():\n    async def scenario():\n        assert await pay(1) == 1\n    asyncio.run(scenario())\n"),
    ("test-no-assert", "tests/test_a.py", "def helper():\n    pay(1)\ndef test_pay():\n    helper()\n",
     "def helper():\n    assert pay(1) == 1\nasync def scenario():\n    helper()\ndef test_pay():\n    asyncio.run(scenario())\n"),
    ("test-no-assert", "tests/test_a.py", "def test_pay():\n    run(1)\n", "def test_pay():\n    _assert_paid(1)\n"),
    ("test-no-assert", "tests/test_a.py", "def test_pay():\n    print(pay(1))\n", "import pytest\ndef test_pay():\n    with pytest.raises(ValueError):\n        pay(0)\n"),
    ("test-no-assert", "tests/a.test.ts", "it('pays', () => {\n  pay(1);\n});\n", "it('pays', () => {\n  expect(pay(1)).toBe(1);\n});\n"),
    ("test-no-assert", "a_test.go", "func TestPay(t *testing.T) {\n\tpay(1)\n\tpay(2)\n}\n", "func TestPay(t *testing.T) {\n\tif pay(1) != 1 {\n\t\tt.Errorf(\"bad\")\n\t}\n}\n"),
    ("test-tautology", "tests/test_a.py", "def test_pay():\n    assert True\n", "def test_pay():\n    assert pay(1)\n"),
    ("test-tautology", "tests/test_a.py", "def test_pay():\n    x = 1\n    assert x == x\n", "def test_pay():\n    x = pay(1)\n    assert x == 1\n"),
    # self-review: `a == a` on an object tests __eq__, which NaN fails, and `obj.flags is obj.flags` tests that a property caches
    ("test-tautology", "tests/test_a.py", "def test_na():\n    assert NA is NA\n", "def test_eq():\n    a = Flags(obj)\n    assert a == a\n"),
    ("test-tautology", "tests/test_a.py", "def test_x():\n    assert 3 == 3\n", "def test_x():\n    assert obj.flags is obj.flags\n"),
    # review of the self-review fixes: an annotated literal and a loop over literals still can't fail
    ("test-tautology", "tests/test_a.py", "def test_x():\n    x: int = 1\n    assert x == x\n", "def test_x(make):\n    x: Flags = make()\n    assert x == x\n"),
    ("test-tautology", "tests/test_a.py", "def test_x():\n    for v in (1, 2):\n        assert v == v\n", "def test_x():\n    for v in (float('nan'), Flags()):\n        assert v == v\n"),
    ("test-tautology", "tests/a.test.ts", "it('x', () => { expect(true).toBe(true); });\n", "it('x', () => { expect(a).toBe(true); });\n"),
    ("test-weak-assert", "tests/test_a.py", "def test_pay():\n    r = pay(1)\n    assert r is not None\n", "def test_pay():\n    r = pay(1)\n    assert r == 1\n"),
    ("test-skipped", "tests/test_a.py", "import pytest\n@pytest.mark.skip\ndef test_pay():\n    assert pay()\n", "def test_pay():\n    assert pay()\n"),
    ("test-skipped", "tests/a.test.js", "it.skip('x', () => {});\n", "it('x', () => { expect(1).toBe(1); });\n"),
    ("test-focused", "tests/a.test.js", "it.only('x', () => { expect(a).toBe(1); });\n", "it('x', () => { expect(a).toBe(1); });\n"),
    ("test-overmocked", "tests/test_a.py", "from unittest.mock import Mock\ndef test_pay():\n    a, b, c, d = Mock(), Mock(), Mock(), Mock()\n    assert pay(a, b, c, d)\n", "from unittest.mock import Mock\ndef test_pay():\n    a = Mock()\n    assert pay(a)\n"),
    ("test-mocks-subject", "tests/test_a.py", "from unittest.mock import patch\n@patch('app.billing.charge')\ndef test_charge_declined(m):\n    m.assert_called()\n", "from unittest.mock import patch\n@patch('app.billing.gateway')\ndef test_charge_declined(m):\n    assert charge(m)\n"),
    ("test-mocks-subject", "tests/test_a.py", "from unittest.mock import Mock\ndef test_tiers(monkeypatch):\n    monkeypatch.setattr(pricing, 'rate', Mock(return_value=1))\n    assert pricing.rate(3) == 1\n", "from unittest.mock import Mock\ndef test_tiers(monkeypatch):\n    monkeypatch.setattr(pricing, 'rate', Mock(return_value=1))\n    assert pricing.total(3) == 1\n"),
    ("test-mocks-subject", "tests/test_a.py", "from unittest.mock import patch\ndef test_tiers():\n    with patch('app.pricing.rate') as rate:\n        rate.return_value = 1\n        assert pricing.rate(3) == 1\n", "from unittest.mock import patch\ndef test_tiers():\n    with patch('app.pricing.rate', wraps=real) as rate:\n        assert pricing.rate(3) == 1\n"),
    ("test-mocks-subject", "tests/test_a.py", "from unittest.mock import patch\n@patch('app.pricing.rate')\ndef test_tiers(rate):\n    assert app.pricing.rate(3)\n", "from app.pricing import rate\nfrom unittest.mock import patch\n@patch('app.pricing.rate')\ndef test_tiers(mocked):\n    assert rate(3)\n"),
    ("test-mocks-subject", "tests/test_a.py", "def test_tiers(monkeypatch):\n    monkeypatch.setattr(pricing, 'rate', lambda n: 1)\n    assert pricing.rate(3) == 1\n", "def test_tiers(monkeypatch):\n    assert pricing.rate(3) == 1\n    monkeypatch.setattr(pricing, 'rate', spy(pricing.rate))\n"),
    ("test-mocks-subject", "tests/test_a.py", "def test_tiers(monkeypatch):\n    monkeypatch.setattr(gate, 'load', lambda: 1)\n    assert gate.load() == 1\n", "def test_tiers(monkeypatch):\n    monkeypatch.setattr(gate, 'load', lambda: 1)\n    assert gate.check(gate.load())\n"),
    ("test-broad-raises", "tests/test_a.py", "import pytest\ndef test_pay():\n    with pytest.raises(Exception):\n        pay()\n", "import pytest\ndef test_pay():\n    with pytest.raises(ValueError):\n        pay()\n"),
    ("test-swallows", "tests/test_a.py", "def test_pay():\n    try:\n        assert pay()\n    except Exception:\n        pass\n", "def test_pay():\n    assert pay()\n"),
    ("test-sleep", "tests/test_a.py", "import time\ndef test_pay():\n    time.sleep(1)\n    assert pay()\n", "def test_pay():\n    assert pay()\n"),
    ("test-generic-name", "tests/test_a.py", "def test_1():\n    assert pay()\n", "def test_pay_rounds_half_even():\n    assert pay()\n"),
    ("test-tautology", "tests/test_a.py", "def test_pay():\n    assert len(pay()) >= 0\n", "def test_pay():\n    assert len(pay()) >= 1\n"),
    ("test-no-assert", "tests/a.rs", "#[test]\nfn pays() {\n    let x = pay();\n    println!(\"{}\", x);\n}\n", "#[test]\nfn pays() {\n    let x = pay().unwrap();\n    println!(\"{}\", x);\n}\n"),
    ("test-no-assert", "tests/a.rs", "#[test]\nfn pays() {\n    let x = pay();\n    println!(\"{}\", x);\n}\n", "fn helper_for_tests() {\n    let x = pay();\n    println!(\"{}\", x);\n}\n"),
    ("test-no-assert", "a_test.go", "func TestPay(t *testing.T) {\n\tpay(1)\n\tpay(2)\n}\n", "func TestPay(t *testing.T) {\n\tpay(1)\n\tcheckPaid(t, 1)\n}\n"),
    # Complexity
    ("high-complexity", "app/a.py", "def f(x):\n" + "".join(f"    if x == {i}:\n        g()\n" for i in range(16)), "def f(x):\n    if x:\n        g()\n"),
    ("high-complexity", "src/a.ts", "function f(x) {\n" + "".join(f"  if (x === {i}) {{ g(); }}\n" for i in range(16)) + "}\n", "function f(x) {\n  if (x) { g(); }\n}\n"),
    ("long-function", "app/a.py", "def f():\n" + "    g()\n" * 105, "def f():\n" + "    g()\n" * 90),
    ("deep-nesting", "app/a.py", "def f(a):\n    if a:\n        if a:\n            if a:\n                if a:\n                    if a:\n                        g()\n", "def f(a):\n    if a:\n        if a:\n            g()\n"),
    ("many-params", "app/a.py", "def f(a, b, c, d, e, f2, g, h):\n    return a\n", "def f(a, b, c, d, e, f2, g):\n    return a\n"),
    ("flag-params", "app/a.py", "def f(a=True, b=False, c=True):\n    return a\n", "def f(a=True, b=False):\n    return a\n"),
    ("god-file", "app/a.py", "x = 1\n" * 1001, "x = 1\n" * 900),
    ("god-class", "app/a.py", "class C:\n" + "".join(f"    def m{i}(self):\n        return {i}\n" for i in range(31)), "class C:\n    def m(self):\n        return 1\n"),
    # Overengineering
    ("pass-through", "app/a.py", "def get_user(user_id):\n    return db.fetch(user_id)\n", "def get_user(user_id):\n    return db.fetch(user_id, active=True)\n"),
    ("pass-through", "app/a.py", "def is_leap(year):\n    return Calculator().calculate(year)\n", "class P(Base):\n    def save(self, item):\n        return super().save(item)\n"),
    ("one-method-class", "app/a.py", "class Sender:\n    def __init__(self, c):\n        self.c = c\n    def send(self, m):\n        return self.c.send(m)\n", "class Sender:\n    def __init__(self, c):\n        self.c = c\n    def send(self, m):\n        return self.c.send(m)\n    def close(self):\n        self.c.close()\n"),
    ("static-only-class", "app/a.py", "class U:\n    @staticmethod\n    def a():\n        return 1\n    @staticmethod\n    def b():\n        return 2\n", "class U:\n    @staticmethod\n    def a():\n        return 1\n    def b(self):\n        return 2\n"),
    ("pattern-one-product", "app/a.py", "class ClientFactory:\n    def create(self):\n        return Client()\n", "class ClientPool:\n    def create(self):\n        return Client()\n"),
    ("async-no-await", "app/a.py", "async def f():\n    return 1\n", "async def f():\n    return await g()\n"),
    # Dead code
    ("unused-import", "app/a.py", "import os\nprint(1)\n", "import os\nprint(os.sep)\n"),
    ("unused-import", "app/a.py", "from os import path, sep\nprint(sep)\n", "from os import path as _unused\nprint(1)\n"),
    ("unreachable-code", "app/a.py", "def f():\n    return 1\n    g()\n", "def f():\n    g()\n    return 1\n"),
    ("dead-branch", "app/a.py", "if False:\n    g()\n", "if flag:\n    g()\n"),
    ("always-true-condition", "app/a.py", "if s == 'paid' or 'void':\n    g()\n", "if s == 'paid' or s == 'void':\n    g()\n"),
    ("commented-out-code", "app/a.py", "x = 1\n# y = compute(x)\n# z = y + 1\n# print(z)\nw = 2\n", "x = 1\n# We keep x small because the parser\n# rejects larger values, and the vendor\n# has no plans to change that.\nw = 2\n"),
    ("commented-out-code", "src/a.rs", "// let y = f(x);\n// let z = y + 1;\n// use_it(z);\nfn g() {}\n", "/// let y = f(x);\n/// let z = y + 1;\n/// use_it(z);\nfn g() {}\n"),
    ("commented-out-code", "src/a.js", "let x = 1;\n// const y = f(x);\n// const z = y + 1;\n// use(z);\nlet w = 2;\n", "let x = 1;\n// Keep x small because the parser rejects\n// larger values, and the vendor has no\n// plans to change that.\nlet w = 2;\n"),
    # Bloat
    ("debug-leftover", "app/a.py", "def f():\n    breakpoint()\n", "def f():\n    return 1\n"),
    ("debug-leftover", "src/a.js", "console.log(x);\n", "logger.info(x);\n"),
    ("debug-leftover", "app/a.py", 'def f():\n    print("DEBUG value", 1)\n', 'def f():\n    print("Result", 1)\n'),
    # Comments
    ("ai-residue", "app/a.py", "# Here's the updated function\ndef f():\n    return 1\n", "# Prices are in cents here\ndef f():\n    return 1\n"),
    ("ai-residue", "app/a.py", "# Fixed: now handles None\nx = 1\n", "# Handles None because the feed omits it\nx = 1\n"),
    ("ai-residue", "app/a.py", "x = 1  # ✅ validated\n", "x = 1  # validated upstream\n"),
    ("narration-comment", "app/a.py", "# increment the counter\ncounter += 1\n", "# retries restart at one because the vendor counts from one\ncounter += 1\n"),
    ("comment-flood", "app/a.py", "# note\n" * 40 + "x = 1\n" * 30, "# note\n" * 5 + "x = 1\n" * 65),
    ("banner-comment", "app/a.py", "# ==========\nx = 1\n# ==========\ny = 1\n# ==========\n", "# note\nx = 1\n"),
    ("missing-docstring", "app/a.py", "def f(a, b, c, d, e):\n    return a\n", 'def f(a, b, c, d, e):\n    """Combine the five inputs."""\n    return a\n'),
    ("docstring-restates-name", "app/a.py", 'def get_user():\n    """Get user."""\n    return 1\n', 'def get_user():\n    """Return the signed-in user, or raise if the session expired."""\n    return 1\n'),
    # Naming
    ("hedge-name", "app/a.py", "def process_v2():\n    return 1\n", "def process():\n    return 1\n"),
    ("hedge-name", "app/a.py", "def load():\n    return 1\ndef load_new():\n    return 2\n", "def new_user():\n    return 1\n"),
    ("vague-name", "app/a.py", "class DataManager:\n    def get(self):\n        return 1\n    def put(self):\n        return 2\n", "class OrderLedger:\n    def get(self):\n        return 1\n    def put(self):\n        return 2\n"),
    ("convention-mismatch", "app/a.py", "def getUser():\n    return 1\ndef load_a():\n    return 1\ndef load_b():\n    return 1\ndef load_c():\n    return 1\n", "def get_user():\n    return 1\n"),
    ("rest-verb-route", "app/a.py", '@app.post("/createUser")\ndef f():\n    return 1\n', '@app.post("/users")\ndef f():\n    return 1\n'),
    # Performance
    ("query-in-loop", "app/a.py", "def f(c, ids):\n    for i in ids:\n        c.execute('SELECT 1', (i,))\n", "def f(c, ids):\n    c.execute('SELECT 1')\n    for i in ids:\n        g(i)\n"),
    ("query-in-loop", "app/a.py", "def f(client, ids):\n    for i in ids:\n        client.get(i)\n", "def f(client):\n    client.get(1)\n"),
    ("query-in-loop", "app/a.py", "def f(c, tables):\n    for t in tables:\n        c.execute('SELECT 1')\n", "def f(c):\n    for t in ('a', 'b'):\n        c.execute('SELECT 1')\n"),
    ("query-in-loop", "app/a.py", "import requests\ndef f(us):\n    for u in us:\n        requests.get(u, timeout=3)\n", "import requests\ndef f(u):\n    requests.get(u, timeout=3)\n"),
    ("query-in-loop", "src/a.js", "for (const x of xs) {\n  await db.query('SELECT 1');\n}\n", "await db.query('SELECT 1');\n"),
    ("query-in-loop", "app/a.py", "def f(store, ids):\n    return [store.get_customer(i) for i in ids]\n", "def f(store, ids):\n    return store.get_customers(ids)\n"),
    ("query-in-loop", "app/a.py", "def f(db, xs):\n    return [db.execute('SELECT 1') for x in xs]\n", "def f(db):\n    return {r[0]: r[1] for r in db.execute('SELECT 1')}\n"),
    ("list-membership-in-loop", "app/a.py", "def f(xs):\n    seen = []\n    for x in xs:\n        seen.remove(x)\n", "def f(xs):\n    seen = set()\n    for x in xs:\n        seen.remove(x)\n"),
    ("list-membership-in-loop", "app/a.py", "def f(xs):\n    seen = []\n    for x in xs:\n        if x not in seen:\n            seen.append(x)\n", "def f(xs):\n    seen = set()\n    for x in xs:\n        if x not in seen:\n            seen.add(x)\n"),
    ("string-concat-loop", "app/a.py", "def f(xs):\n    out = ''\n    for x in xs:\n        out += x\n    return out\n", "def f(xs):\n    n = 0\n    for x in xs:\n        n += x\n    return n\n"),
    ("nested-same-collection", "app/a.py", "def f(xs):\n    for a in xs:\n        for b in xs:\n            g(a, b)\n", "def f(xs, ys):\n    for a in xs:\n        for b in ys:\n            g(a, b)\n"),
    ("nested-loops", "app/a.py", "def f(a, b, c):\n    for x in a:\n        for y in b:\n            for z in c:\n                g(x, y, z)\n", "def f(a, b):\n    for x in a:\n        for y in b:\n            g(x, y)\n"),
    ("sort-in-loop", "app/a.py", "def f(xs):\n    top = []\n    for x in xs:\n        top.append(x)\n        top.sort()\n", "def f(xs):\n    y = sorted(xs)\n    for x in y:\n        g(x)\n"),
    # self-review: sorting each item's own values is linear in the items, not a re-sort of what grows
    ("sort-in-loop", "app/a.py", "def f(rows):\n    seen = []\n    for r in rows:\n        seen.append(r)\n        best = sorted(seen)[0]\n", "def f(rows):\n    for r in rows:\n        tags = sorted(r.tags)\n        emit(tags)\n"),
    # review of the self-review fixes: a list carried over or never changed is sorted again each pass, at module level too; a pass's own listing isn't
    ("sort-in-loop", "app/a.py", "def f(rows):\n    items = []\n    for r in rows:\n        items = sorted(items + [r])\n", "import os\ndef f(paths):\n    for p in paths:\n        names = sorted(os.listdir(p))\n        emit(names)\n"),
    ("sort-in-loop", "app/a.py", "for r in rows:\n    top = sorted(scores, reverse=True)[:10]\n    emit(r, top)\n", "for r in rows:\n    line = sorted(r.items(), key=len)\n    emit(line)\n"),
    ("sort-in-loop", "app/a.py", "def f(rows):\n    seen = {}\n    for r in rows:\n        seen[r.k] = r\n        best = sorted(seen)[0]\n", "def f(q):\n    while q:\n        job = q.pop()\n        run(sorted(job.steps))\n"),
    # third review: sorting each element in place, or calling a method on an object the loop adds to, isn't a re-sort; a growing prefix is
    ("sort-in-loop", "app/a.py", "def f(xs):\n    for i in range(len(xs)):\n        w = sorted(xs[:i + 1])\n        emit(w)\n", "def f(index):\n    for k in index:\n        index[k] = sorted(index[k])\n"),
    ("sort-in-loop", "app/a.py", "def f(rows, cache):\n    for r in rows:\n        cache.update(r)\n        emit(sorted(cache))\n", "def f(users, session, out):\n    for user in users:\n        session.add(user)\n        out.append(sorted(session.scalars(user.roles)))\n"),
    ("sort-in-loop", "app/a.py", "def f(rows, scores):\n    for r in rows:\n        try:\n            go(r)\n        except ValueError as e:\n            emit(sorted(scores))\n", "def f(rows):\n    for r in rows:\n        try:\n            go(r)\n        except ValueError as e:\n            emit(sorted(e.args))\n"),
    # second review: an index, a with target or an unpacked value made on this pass is this pass's own
    ("sort-in-loop", "app/a.py", "def f(rows):\n    seen = []\n    for r in rows:\n        seen += [r]\n        emit(sorted(seen))\n", "def f(d, out):\n    for k in d:\n        out[k] = sorted(d[k])\n"),
    ("sort-in-loop", "app/a.py", "import numpy as np\ndef f(m, rows):\n    for r in rows:\n        emit(r, np.sort(m))\n", "def f(paths, out):\n    for p in paths:\n        with open(p) as fh:\n            out.append(sorted(fh))\n"),
    ("sort-in-loop", "app/a.py", "def f(rows, out):\n    for r in rows:\n        out.append(sorted(out))\n", "def f(rows, out):\n    for row in rows:\n        key, vals = row\n        out.append(sorted(vals))\n"),
    ("regex-compile-loop", "app/a.py", "import re\ndef f(xs):\n    for x in xs:\n        re.compile(x)\n", "import re\nP = re.compile('a')\n"),
    ("dataframe-iterrows", "app/a.py", "def f(df):\n    for i, row in df.iterrows():\n        g(row)\n", "def f(df):\n    return df.sum()\n"),
    ("dataframe-grow-loop", "app/a.py", "import numpy as np\ndef f(xs):\n    out = np.array([])\n    for x in xs:\n        out = np.append(out, x)\n", "import numpy as np\ndef f(xs):\n    return np.array(list(xs))\n"),
    ("python-loop-over-array", "app/a.py", "import numpy as np\ndef f(a):\n    for i in range(len(a)):\n        a[i] = a[i] * 2\n", "def f(a):\n    for i in range(len(a)):\n        a[i] = a[i] * 2\n"),
    ("materialize-all", "app/a.py", "def f(c):\n    return c.fetchall()\n", "def f(c):\n    return c.fetchmany(10)\n"),
    ("blocking-in-async", "app/a.py", "import time\nasync def f():\n    time.sleep(1)\n    await g()\n", "import asyncio\nasync def f():\n    await asyncio.sleep(1)\n"),
    ("unbounded-concurrency", "app/a.py", "import asyncio\nasync def f(xs):\n    await asyncio.gather(*[g(x) for x in xs])\n", "import asyncio\nasync def f(xs):\n    sem = asyncio.Semaphore(5)\n    await asyncio.gather(*[g(x, sem) for x in xs])\n"),
    ("unbounded-concurrency", "src/a.js", "await Promise.all(xs.map(f));\n", "await limit(xs, f);\n"),
    ("missing-timeout", "app/a.py", "import requests\nrequests.get(u)\n", "import requests\nrequests.get(u, timeout=5)\n"),
    ("unbounded-cache", "app/a.py", "from functools import lru_cache\n@lru_cache(maxsize=None)\ndef f(x):\n    return x\n", "from functools import lru_cache\n@lru_cache(maxsize=100)\ndef f(x):\n    return x\n"),
    ("io-in-loop", "app/a.py", "def f(xs):\n    for x in xs:\n        open(x).close()\n", "def f(x):\n    open(x).close()\n"),
    ("transfer-in-loop", "app/a.py", "import torch\ndef f(xs):\n    for x in xs:\n        v = x.item()\n", "import torch\ndef f(x):\n    v = x.item()\n"),
    ("remote-get-in-loop", "app/a.py", "import ray\ndef f(xs):\n    for x in xs:\n        ray.get(g.remote(x))\n", "import ray\ndef f(xs):\n    return ray.get([g.remote(x) for x in xs])\n"),
    ("oversubscription", "app/a.py", "import numpy as np\nfrom multiprocessing import Pool\ndef f():\n    return Pool()\n", "from multiprocessing import Pool\ndef f():\n    return Pool()\n"),
    ("select-star", "q.sql", "SELECT * FROM t;\n", "SELECT a FROM t;\n"),
    ("not-in-subquery", "q.sql", "SELECT a FROM t WHERE a NOT IN (SELECT a FROM u);\n", "SELECT a FROM t WHERE NOT EXISTS (SELECT 1 FROM u);\n"),
    ("unbounded-write", "q.sql", "DELETE FROM users;\n", "DELETE FROM users WHERE id = 1;\n"),
    # Scalability
    ("process-local-state", "app/a.py", "sessions = {}\ndef login(u):\n    sessions[u] = 1\n", "sessions = {}\ndef read(u):\n    return sessions.get(u)\n"),
    ("unpaginated-query", "app/a.py", "@app.get('/users')\ndef users():\n    return User.query.all()\n", "@app.get('/users')\ndef users():\n    return User.query.limit(50).offset(0)\n"),
    ("import-time-io", "app/a.py", "import requests\nCONFIG = requests.get('http://x', timeout=3).json()\n", "import requests\ndef load():\n    return requests.get('http://x', timeout=3).json()\n"),
    ("hardcoded-host", "app/a.py", 'URL = "http://localhost:8000/api"\n', 'URL = os.environ["URL"]\n'),
    ("absolute-path", "app/a.py", 'P = "/Users/sam/data.csv"\n', 'P = "data.csv"\n'),
    # Architecture
    ("sql-in-handler", "app/a.py", "@app.get('/u')\ndef u():\n    db.execute('SELECT id FROM users')\n", "@app.get('/u')\ndef u():\n    return load_users()\n"),
    ("lsp-violation", "app/a.py", "class A(B):\n    def go(self):\n        raise NotImplementedError\n", "class A(B):\n    def go(self):\n        return 1\n"),
    ("global-statement", "app/a.py", "n = 0\ndef f():\n    global n\n    n = 1\n", "n = 0\ndef f():\n    return n\n"),
    # Usability
    ("generic-exception", "app/a.py", "def f():\n    raise Exception('nope')\n", "def f():\n    raise ValueError('nope')\n"),
    ("opaque-error", "app/a.py", "def f():\n    raise ValueError('Invalid input')\n", "def f(x):\n    raise ValueError(f'bad quantity {x}')\n"),
    ("inconsistent-return", "app/a.py", "def f(x):\n    if x:\n        return 'ok'\n    return False\n", "def f(x):\n    if x:\n        return 'ok'\n    return 'no'\n"),
    ("print-in-library", "app/a.py", "import logging\ndef f():\n    print('x')\n    logging.info('y')\n", "import logging\ndef f():\n    logging.info('y')\n"),
    ("a11y-missing", "src/a.tsx", 'const a = <img src="x.png" />;\n', 'const a = <img src="x.png" alt="logo" />;\n'),
    # Reinvention
    ("handrolled-retry", "app/a.py", "import time\ndef f():\n    for i in range(3):\n        try:\n            return g()\n        except OSError:\n            time.sleep(1)\n", "def f():\n    for i in range(3):\n        try:\n            g(i)\n        except OSError:\n            log(i)\n"),
    ("handrolled-csv", "app/a.py", "def f(fh):\n    for line in fh:\n        a = line.split(',')\n", "import csv\ndef f(fh):\n    for row in csv.reader(fh):\n        g(row)\n"),
    ("handrolled-dotenv", "app/a.py", "def f():\n    with open('.env') as e:\n        return e.read()\n", "def f():\n    with open('settings.ini') as e:\n        return e.read()\n"),
    ("handrolled-argv", "app/a.py", "import sys\nif sys.argv[1] == '--help':\n    print(sys.argv[2])\n", "import sys\nname = sys.argv[1]\n"),
    ("handrolled-argv", "app/a.py", "import sys\nverbose = '--v' in sys.argv\nquiet = '--q' in sys.argv\n", "import sys\nname = sys.argv[1]\nodd = sys.platform == '--z'\n"),
    ("handrolled-url", "app/a.py", 'def f(a, b):\n    return f"https://x.dev/s?a={a}&b={b}"\n', 'def f(a):\n    return f"https://x.dev/s/{a}"\n'),
    ("handrolled-json", "app/a.py", """def f(a):\n    return f'{{"name": "{a}"}}'\n""", "import json\ndef f(a):\n    return json.dumps({'name': a})\n"),
    ("handrolled-json", "app/a.py", """def f(a):\n    return '{"to": "' + a + '"}'\n""", """import json\ndef f(a):\n    return '{"to": ' + json.dumps(a) + '}'\n"""),
    ("handrolled-html-parse", "app/a.py", "import re\ndef f(h):\n    return re.findall('<a href=(.*)>', h)\n", "import re\ndef f(h):\n    return re.findall('[0-9]+', h)\n"),
    ("handrolled-memo", "app/a.py", "CACHE = {}\ndef f(k):\n    if k in CACHE:\n        return CACHE[k]\n    CACHE[k] = g(k)\n    return CACHE[k]\n", "def f(k):\n    return g(k)\n"),
    ("handrolled-helper", "app/a.py", "def chunks(xs, n):\n    out = []\n    return out\n", "def split_into_invoices(xs, n):\n    out = []\n    return out\n"),
    ("handrolled-helper", "app/a.py", "class Strategy:\n    def is_leap(self, y):\n        return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)\n", "def every_fourth(y):\n    return y % 4 == 0\n"),
    # Language practice
    ("mutable-default", "app/a.py", "def f(x=[]):\n    return x\n", "def f(x=None):\n    return x or []\n"),
    ("frozen-default", "app/a.py", "import datetime\ndef f(at=datetime.datetime.now()):\n    return at\n", "def f(at=None):\n    return at\n"),
    ("frozen-default", "app/a.py", "import time\nclass J:\n    created: float = time.time()\n", "from dataclasses import dataclass, field\nimport time\n@dataclass\nclass J:\n    created: float = field(default_factory=time.time)\n"),
    ("missing-await", "src/a.js", "async function f() {\n  const r = await fetch(u);\n  const d = r.json();\n  return d.x;\n}\n", "async function f() {\n  const r = await fetch(u);\n  const d = await r.json();\n  return d.x;\n}\n"),
    ("missing-await", "src/a.js", "async function f() {\n  const r = await fetch(u);\n  const d = r.json();\n  return d.x;\n}\n", "async function f() {\n  const res = await fetch(u);\n  return res.json();\n}\nfetch(u).then((r) => (r.ok ? r.json() : null));\n"),
    ("missing-await", "app/a.py", "import asyncio\nasync def f():\n    asyncio.sleep(1)\n", "import asyncio\nasync def f():\n    await asyncio.sleep(1)\n"),
    ("float-money", "app/a.py", "def annual(price_cents):\n    return int(price_cents * 12 * 0.85)\n", "def annual(width):\n    return int(width * 12 * 0.85)\n"),
    ("unparseable", "app/a.py", "def f(:\n    x = 1\n", "def f():\n    x = 1\n"),
    ("deprecated-api", "app/a.py", "import datetime\nnow = datetime.datetime.utcnow()\n", "import datetime\nnow = datetime.datetime.now(datetime.timezone.utc)\n"),
    ("deprecated-api", "app/a.py", "import openai\nr = openai.ChatCompletion.create(model='x')\n", "client = make_client()\n"),
    ("deprecated-api", "a.go", "b, _ := ioutil.ReadAll(r)\n", "b, _ := io.ReadAll(r)\n"),
    ("float-money", "app/a.py", "total = float(price)\n", "ratio = float(width)\n"),
    ("float-money", "app/a.py", "total = float(order.amount)\n", "ratio = float(shape.width)\n"),
    ("float-money", "app/a.py", "due = round(order.total, 2)\n", "share = round(correct / total, 2)\n"),
    ("float-money", "app/a.py", "total = float(order.amount)\n", "tries = float(payment.retry_count)\n"),
    ("float-money", "app/a.py", "total = float(order.amount)\n", "guess = float(cost_model.predict(a))\n"),
    ("float-money", "app/a.py", "due = round(subtotal * 1.08, 2)\n", "due = round(1.08 * 3, 2)\n"),
    ("float-money", "app/a.py", "due = round(amount / 3, 2)\n", "due = round(3 / amount, 2)\n"),
    ("float-money", "app/a.py", "due = round(-amount, 2)\n", "due = round(-width, 2)\n"),
    ("float-money", "app/a.py", "due = float(total or 0)\n", "due = float(width or 0)\n"),
    ("float-money", "app/a.py", "due = float(prices[0])\n", "due = float(widths[0])\n"),
    ("float-money", "app/a.py", "due = float(get_price())\n", "due = float(get_width())\n"),
    ("float-money", "app/a.py", "due = int(amount * 1.5 / 2)\n", "due = int(width * 1.5 / 2)\n"),
    ("float-money", "t.sql", "CREATE TABLE t (price REAL);\n", "CREATE TABLE t (price NUMERIC(12,2));\n"),
    ("star-import", "app/a.py", "from os import *\n", "from os import sep\n"),
    ("naive-datetime", "app/a.py", "import datetime\nnow = datetime.datetime.now()\n", "import datetime\nnow = datetime.datetime.now(datetime.timezone.utc)\n"),
    ("resource-no-context", "app/a.py", "f = open('x')\n", "with open('x') as f:\n    g(f)\n"),
    ("async-foreach", "src/a.js", "xs.forEach(async (x) => { await f(x); });\n", "for (const x of xs) { await f(x); }\n"),
    ("ts-any", "src/a.ts", "function f(x: any) {}\n", "function f(x: unknown) {}\n"),
    ("go-defer-in-loop", "a.go", "for _, p := range ps {\n\tf, _ := os.Open(p)\n\tdefer f.Close()\n}\n", "f, err := os.Open(p)\ndefer f.Close()\n"),
    ("shell-no-strict", "a.sh", "#!/bin/sh\n" + "echo hi\n" * 12, "#!/bin/sh\nset -eu\n" + "echo hi\n" * 12),
    ("shell-unquoted-rm", "a.sh", "#!/bin/sh\nset -e\nrm -rf $DIR\n", '#!/bin/sh\nset -e\nrm -rf "$DIR"\n'),
    ("shell-syntax", "a.sh", "#!/bin/bash\nset -e\nif true; then\n", "#!/bin/bash\nset -e\nif true; then echo y; fi\n"),
    ("shell-bashism", "a.sh", "#!/bin/sh\nset -e\n[[ -n $x ]] && echo y\n", "#!/bin/bash\nset -e\n[[ -n $x ]] && echo y\n"),
    ("shell-unquoted-path", "a.sh", "#!/bin/sh\nset -e\ncp $a b\n", '#!/bin/sh\nset -e\ncp "$a" b\n'),
    ("shell-cd-unchecked", "a.sh", "#!/bin/sh\ncd /tmp\nmake\n", "#!/bin/sh\ncd /tmp || exit 1\nmake\n"),
    ("shell-ls-parse", "a.sh", "#!/bin/sh\nset -e\nfor f in $(ls); do echo \"$f\"; done\n", "#!/bin/sh\nset -e\nfor f in *; do echo \"$f\"; done\n"),
    ("shell-word-split", "a.sh", "#!/bin/sh\nset -e\nfor f in $(find . -name x); do echo \"$f\"; done\n", "#!/bin/sh\nset -e\nfind . -name x -print0 | xargs -0 echo\n"),
    ("shell-nonportable", "a.sh", "#!/bin/sh\nset -e\ngrep -P x y\n", "#!/bin/sh\nset -e\ngrep -E x y\n"),
    ("shell-masked-failure", "a.sh", "#!/bin/bash\nf() {\n  local x=$(cmd)\n}\n", "#!/bin/bash\nf() {\n  local x\n  x=$(cmd)\n}\n"),
    ("shell-rm-unguarded", "a.sh", '#!/bin/sh\nset -e\nrm -rf "$d"/*\n', '#!/bin/sh\nset -e\nrm -rf "${d:?}"/*\n'),
    ("shell-tmp-no-trap", "a.sh", "#!/bin/sh\nset -e\nt=$(mktemp)\n", "#!/bin/sh\nset -e\nt=$(mktemp)\ntrap 'rm -f \"$t\"' EXIT\n"),
    ("shell-outgrown", "a.sh", "#!/bin/sh\nset -e\n" + "echo hi\n" * 301, "#!/bin/sh\nset -e\n" + "echo hi\n" * 200),
    ("namespace-in-header", "a.hpp", "using namespace std;\n", "using std::string;\n"),
    ("structured-concurrency-escape", "A.kt", "GlobalScope.launch { f() }\n", "scope.launch { f() }\n"),
]

# Rules that need several files. (rule, files where it fires, near-miss files where it doesn't)
_SIX_LINES = "    a = x + 1\n    b = a * 2\n    c = b - 3\n    d = c / 4\n    e = d + a\n    h = e * b\n    i = h - c\n    j = i + d\n    return j\n"
RENAMED = """function {f}(x) {{
  let {v} = 0;
  const {w}s = load(x);
  for (const {w} of {w}s) {{
    if ({w}.ok) {{
      {v} += {w}.size;
    }} else if ({w}.bad) {{
      throw new Error({w}.why);
    }}
    await save({w}, {v});
    log.info({w}.id, {v}, "x");
    while ({v} > 10) {{
      {v} = {v} - 1;
    }}
    return {v} * {w}.rate + 3;
  }}
}}
"""
PROJECT = [
    ("private-import", {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["pydantic"]\n', "app/a.py": "from pydantic._internal import _model_construction\nprint(_model_construction)\n"},
     {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["pydantic"]\n', "app/__init__.py": "", "app/_helpers.py": "x = 1\n",
      "app/a.py": "import _thread\nfrom pydantic import BaseModel\nfrom app import _helpers\nprint(_thread, BaseModel, _helpers)\n"}),
    ("phantom-import", {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["requests"]\n', "app/a.py": "import flask_superauth\nprint(flask_superauth)\n"},
     {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["requests"]\n', "app/a.py": "import requests\nprint(requests)\n"}),
    ("phantom-import", {"pyproject.toml": '[project]\nname = "x"\ndependencies = [\n  "httpx[socks]>=0.27",\n]\n', "app/a.py": "import flask_superauth\nprint(flask_superauth)\n"},
     {"pyproject.toml": '[project]\nname = "x"\ndependencies = [\n  "httpx[socks]>=0.27",\n  "mcp>=1",  # after the extras\n]\n', "app/a.py": "import httpx\nimport mcp\nprint(httpx, mcp)\n"}),
    ("phantom-import", {"pyproject.toml": '[project]\nname = "x"\n', "uv.lock": 'name = "fastapi"\n', "app/a.py": "import sse_starlette\nprint(sse_starlette)\n"},
     {"pyproject.toml": '[project]\nname = "x"\n', "uv.lock": 'name = "sse-starlette"\n', "app/a.py": "import sse_starlette\nprint(sse_starlette)\n"}),
    ("phantom-local-import", {"src/pkg/__init__.py": "", "src/pkg/a.py": "from pkg.foundation.tools import missing\nprint(missing)\n", "src/pkg/foundation/__init__.py": "", "src/pkg/foundation/tools.py": "def real():\n    return 1\n"},
     {"src/pkg/__init__.py": "", "src/pkg/a.py": "import json\nimport tools\nprint(json.dumps(1), tools.other)\n", "src/pkg/foundation/__init__.py": "", "src/pkg/foundation/json.py": "def real():\n    return 1\n", "src/pkg/foundation/tools.py": "def real():\n    return 1\n"}),
    ("phantom-local-import", {"app/__init__.py": "", "app/b.py": "def real():\n    return 1\n", "app/a.py": "from app import b\nprint(b.missing)\n"},
     {"app/__init__.py": "from .settings import settings\n", "app/settings.py": "class S:\n    token = 1\nsettings = S()\n", "app/a.py": "from app import settings\nprint(settings.token)\n"}),
    ("phantom-local-import", {"app/__init__.py": "", "app/a.py": "from app.b import missing\nprint(missing)\n", "app/b.py": "def real():\n    return 1\n"},
     {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["alembic"]\n', "storage/__init__.py": "", "storage/alembic/__init__.py": "", "storage/alembic/env.py": "from alembic import op\nprint(op)\n"}),
    ("phantom-import", {"package.json": '{"dependencies": {"react": "1"}}', "a.js": "import x from 'left-pad-super';\nuse(x);\n"},
     {"package.json": '{"dependencies": {"react": "1"}}', "a.js": "import x from 'react';\nimport fs from 'node:fs';\nimport path from 'path';\nuse(x, fs, path);\n"}),
    ("phantom-import", {"Cargo.toml": '[package]\nname = "demo"\n[dependencies]\nserde = "1"\n', "src/a.rs": "use made_up_crate::x;\n"},
     {"Cargo.toml": '[package]\nname = "demo"\n[dependencies]\nserde = "1"\n', "src/a.rs": "use serde::Serialize;\nuse std::fmt;\nuse Mode::*;\n", "tests/t.rs": "use demo::run;\n"}),
    ("phantom-import", {"go.mod": "module ex.com/app\nrequire github.com/a/b v1.0.0\n", "a.go": 'package a\nimport "github.com/z/y"\n'},
     {"go.mod": "module ex.com/app\nrequire github.com/a/b v1.0.0\n", "a.go": 'package a\nimport "github.com/a/b/c"\nimport "fmt"\n'}),
    ("phantom-local-import", {"app/__init__.py": "", "app/a.py": "from app.b import missing\nprint(missing)\n", "app/b.py": "def real():\n    return 1\n"},
     {"app/__init__.py": "", "app/a.py": "from app.b import real\nprint(real)\n", "app/b.py": "def real():\n    return 1\n"}),
    ("phantom-local-import", {"a.ts": "import { x } from './nope';\nuse(x);\n"}, {"a.ts": "import { x } from './b';\nuse(x);\n", "b.ts": "export const x = 1;\n"}),
    # self-review: the listing skips build/ and vendor/, and a folder with a package.json resolves through its "main"
    ("phantom-local-import", {"pkg/__init__.py": "", "pkg/a.py": "from .nope import make\nmake()\n"},
     {"pkg/__init__.py": "", "pkg/a.py": "from .build import make\nmake()\n", "pkg/build/__init__.py": "def make():\n    return 1\n"}),
    ("phantom-local-import", {"src/a.js": "const qr = require('../lib/nope');\nqr();\n"},
     {"src/a.js": "const qr = require('../vendor/qr');\nconst w = require('../lib/widget');\nqr(w);\n", "vendor/qr/index.js": "module.exports = 1;\n",
      "lib/widget/package.json": "{\"main\": \"dist/widget.js\"}\n"}),
    # review of the self-review fixes: a module named like a skipped folder that doesn't exist is still missing, and a submodule in one isn't
    ("phantom-local-import", {"pkg/__init__.py": "", "pkg/a.py": "from .env import load_settings\nload_settings()\n"},
     {"pkg/__init__.py": "", "pkg/a.py": "from . import build\nimport pkg.vendor.qr\nbuild.make()\npkg.vendor.qr.encode()\n", "pkg/build/__init__.py": "def make():\n    return 1\n",
      "pkg/vendor/__init__.py": "", "pkg/vendor/qr.py": "def encode():\n    return 1\n"}),
    # third review: in JavaScript a package often imports its own dist/ before a build; in Python an out/ that isn't there is missing
    ("phantom-local-import", {"pkg/__init__.py": "", "pkg/a.py": "from .out.formatters import render\nrender()\n"},
     {"index.js": "module.exports = require('./dist');\n", "bin/cli.js": "require('../build').run();\n"}),
    # second review: a build output may not be built yet in a fresh clone
    ("phantom-local-import", {"bin/cli.js": "require('../lib/cli.js').main();\n"},
     {"bin/cli.js": "require('../dist/cli.js').main();\n", "index.js": "module.exports = require('./build/Release/addon.node');\n"}),
    ("phantom-attribute", {"app/a.py": "import os.path\nprint(os.path.exist('x'))\n"}, {"app/a.py": "import os.path\nprint(os.path.exists('x'))\n"}),
    ("phantom-attribute", {"app/a.py": "import json\nprint(json.parse('1'))\n"}, {"app/a.py": "import json\nprint(json.loads('1'))\n"}),
    ("undefined-name", {"app/a.py": "def f():\n    return helper_that_was_never_written(1)\n"}, {"app/a.py": "def helper(x):\n    return x\ndef f():\n    return helper(1)\n"}),
    ("undeclared-dependency", {"pyproject.toml": '[project]\nname = "x"\ndependencies = []\n', "app/a.py": "import pytest\nprint(pytest)\n"},
     {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["pytest"]\n', "app/a.py": "import pytest\nprint(pytest)\n"}),
    ("committed-secret-file", {".env": "A=1\n"}, {".env.example": "A=\n"}),
    ("missing-auth", {"app/a.py": "".join(f"@app.get('/u{i}')\n@login_required\ndef view{i}():\n    return 1\n" for i in range(3)) + "@app.get('/export')\ndef export_all():\n    return 1\n"},
     {"app/a.py": "".join(f"@app.get('/u{i}')\n@login_required\ndef view{i}():\n    return 1\n" for i in range(3)) + "@app.get('/health')\ndef health():\n    return 1\n"}),
    ("no-tests", {"app/a.py": "x = 1\n" * 60}, {"app/a.py": "x = 1\n" * 60, "tests/test_a.py": "def test_x():\n    assert 1\n"}),
    ("module-untested", {"app/core.py": "def calculate_invoice():\n" + "    x = 1\n" * 60, "tests/test_b.py": "def test_x():\n    assert 1 == 2\n"},
     {"app/core.py": "def calculate_invoice():\n" + "    x = 1\n" * 60, "tests/test_core.py": "from app.core import calculate_invoice\ndef test_x():\n    assert calculate_invoice() == 2\n"}),
    ("clone-block", {"a.py": "def f(x):\n" + _SIX_LINES, "b.py": "def g(x):\n" + _SIX_LINES},
     {"a.py": "def f(x):\n" + _SIX_LINES, "b.py": "def g(x):\n    return x\n"}),
    ("clone-function", {"a.py": "def f(x):\n    a = x + 1\n    b = a * 2\n    c = b - 3\n    d = c / 4\n    return d\n", "b.py": "def g(y):\n    p = y + 7\n    q = p * 9\n    r = q - 8\n    s = r / 6\n    return s\n"},
     {"a.py": "def f(x):\n    a = x + 1\n    b = a * 2\n    c = b - 3\n    d = c / 4\n    return d\n", "b.py": "def g(y):\n    if y:\n        return 1\n    return 2\n"}),
    # review of the self-review fixes: pull-up-method names one method per pair of classes, so a second identical method is still a clone
    ("clone-function", {"a.py": "class P:\n    def go(self):\n        a = self.x\n        b = a + 1\n        c = b + 2\n        d = c + 3\n        return d\n    def stop(self):\n        a = self.y\n        b = a * 1\n        c = b * 2\n        d = c * 3\n        return d\n",
                        "b.py": "class Q:\n    def go(self):\n        a = self.x\n        b = a + 1\n        c = b + 2\n        d = c + 3\n        return d\n    def stop(self):\n        a = self.y\n        b = a * 1\n        c = b * 2\n        d = c * 3\n        return d\n"},
     {"a.py": "def f(x):\n    return x\n"}),
    # self-review: identical methods of sibling classes are pull-up-method's to report, once
    ("clone-function", {"a.py": "def f(x):\n    a = x + 1\n    b = a * 2\n    c = b - 3\n    d = c / 4\n    return d\n", "b.py": "def g(y):\n    p = y + 7\n    q = p * 9\n    r = q - 8\n    s = r / 6\n    return s\n"},
     {"a.py": "class P:\n    def go(self):\n        a = self.x\n        b = a + 1\n        c = b + 2\n        d = c + 3\n        return d\n", "b.py": "class Q:\n    def go(self):\n        a = self.x\n        b = a + 1\n        c = b + 2\n        d = c + 3\n        return d\n"}),
    ("clone-renamed", {"a.js": RENAMED.format(v="total", w="item", f="sum"), "b.js": RENAMED.format(v="count", w="row", f="add")},
     {"a.js": "function f(a) {\n  use(a);\n}\n", "b.js": "function g(b) {\n  log(b);\n}\n"}),
    ("diverged-twin", {"a.py": "def parse_date(s):\n    x = s.strip()\n    y = x.split('-')\n    z = y[0]\n    return z\n", "b.py": "def parse_date(s):\n    if not s:\n        return None\n    for i in s:\n        g(i)\n    return s\n"},
     {"a.py": "def parse_date(s):\n    x = s.strip()\n    y = x.split('-')\n    z = y[0]\n    return z\n", "b.py": "def parse_time(s):\n    return s\n"}),
    ("parallel-verbs", {"a.py": "def fetch_user(i):\n    a = i\n    b = a\n    return b\n", "b.py": "def get_user(j):\n    if j:\n        return 1\n    c = j\n    return c\n"},
     {"a.py": "def fetch_user(i):\n    a = i\n    b = a\n    return b\n", "b.py": "def delete_user(j):\n    if j:\n        return 1\n    c = j\n    return c\n"}),
    ("single-impl-abstraction", {"a.py": "from abc import ABC, abstractmethod\nclass Sink(ABC):\n    @abstractmethod\n    def put(self):\n        ...\nclass Only(Sink):\n    def put(self):\n        return 1\n"},
     {"a.py": "from abc import ABC, abstractmethod\nclass Sink(ABC):\n    @abstractmethod\n    def put(self):\n        ...\nclass One(Sink):\n    def put(self):\n        return 1\nclass Two(Sink):\n    def put(self):\n        return 2\n"}),
    ("deep-inheritance", {"a.py": "class A: pass\nclass B(A): pass\nclass C(B): pass\nclass D(C): pass\nclass E(D): pass\n"}, {"a.py": "class A: pass\nclass B(A): pass\n"}),
    ("unreferenced-def", {"a.py": "def nobody_calls_me():\n    return 1\n"}, {"a.py": "def somebody_calls_me():\n    return 1\nprint(somebody_calls_me())\n"}),
    ("orphan-module", {"app/__init__.py": "", "app/lonely.py": "def lonely_helper():\n    return 1\nprint(lonely_helper())\nprint(2)\nprint(3)\n"},
     {"app/__init__.py": "from app.used import used_helper\n", "app/used.py": "def used_helper():\n    return 1\nprint(1)\nprint(2)\nprint(3)\n"}),
    ("scratch-file", {"app/service_old.py": "x = 1\n"}, {"app/service.py": "x = 1\n"}),
    ("scratch-file", {"app/debug_payment.py": "x = 1\n"}, {"app/payment.py": "x = 1\n"}),
    ("ai-report-file", {"IMPLEMENTATION_SUMMARY.md": "done\n"}, {"README.md": "docs\n"}),
    ("unused-dependency", {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["requests"]\n', "app/a.py": "x = 1\n"}, {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["requests"]\n', "app/a.py": "import requests\nprint(requests)\n"}),
    ("competing-dependencies", {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["requests", "httpx"]\n'}, {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["requests"]\n'}),
    ("utility-bucket", {"app/utils.py": "x = 1\n" * 310}, {"app/utils.py": "x = 1\n" * 50}),
    ("large-binary", {"data.bin": "x" * 6_000_000}, {"data.bin": "x" * 100}),
    ("import-cycle", {"a.py": "import b\nprint(b)\n", "b.py": "import a\nprint(a)\n"}, {"a.py": "import b\nprint(b)\n", "b.py": "print(1)\n"}),
    ("hub-module", {**{f"m{i}.py": "import hub\nprint(hub)\n" for i in range(32)}, "hub.py": "".join(f"import n{i}\nprint(n{i})\n" for i in range(16)), **{f"n{i}.py": "print(1)\n" for i in range(16)}},
     {"a.py": "import b\nprint(b)\n", "b.py": "print(1)\n"}),
    ("unreferenced-setting", {"app/config.py": "import os\nNET_TERMS = int(os.environ.get('NET_TERMS', '14'))\nNAME = os.environ['NAME']\n", "app/a.py": "from app.config import NAME\nprint(NAME)\n"},
     {"app/config.py": "import os\nNET_TERMS = int(os.environ.get('NET_TERMS', '14'))\n", "app/a.py": "from app.config import NET_TERMS\nprint(NET_TERMS)\n"}),
    ("checks-hidden-by-config", {"pyproject.toml": '[tool.pytest.ini_options]\naddopts = "-q --ignore=tests/test_refunds.py"\n'}, {"pyproject.toml": '[tool.pytest.ini_options]\naddopts = "-q"\n'}),
    ("duplicate-config", {"app/config.py": "x = 1\n", "app/settings.py": "y = 1\n"}, {"app/config.py": "x = 1\n"}),
    ("base-class-bypassed", {"a.py": "class BaseStore:\n    def get(self):\n        return 1\n    def put(self):\n        return 2\nclass RedisStore(BaseStore):\n    pass\nclass S3Store(BaseStore):\n    pass\nclass MemoryStore:\n    def get(self):\n        return 3\n    def put(self):\n        return 4\n"},
     {"a.py": "class BaseStore:\n    def get(self):\n        return 1\n    def put(self):\n        return 2\nclass RedisStore(BaseStore):\n    pass\nclass S3Store(BaseStore):\n    pass\nclass MemoryStore(BaseStore):\n    def get(self):\n        return 3\n"}),
    ("unreferenced-def", {"app/a.py": "def lonely_helper(x):\n    return x\n"}, {"app/a.py": "def go(x):\n    return x\n\n\nprint(go(1))\n"}),  # names under 3 characters aren't counted, so they can't be judged
    ("unused-option", {"app/net.py": "def fetch(url, retries=3):\n    return url * retries\n", "app/a.py": "from app.net import fetch\nprint(fetch('x'))\n"},
     {"app/net.py": "def fetch(url, retries=3):\n    return url * retries\n", "app/a.py": "from app.net import fetch\nprint(fetch('x', retries=2))\n"}),
    ("unused-option", {"app/net.py": "def fetch(url, retries=3):\n    return url * retries\n", "app/a.py": "from app.net import fetch\nprint(fetch('x'))\n"},
     {"app/net.py": "def fetch(url, retries=3):\n    return url * retries\n", "app/a.py": "from app.net import fetch\nprint(fetch('x', 2))\n"}),
    ("unused-option", {"app/net.py": "class Client:\n    def __init__(self, url, timeout=3):\n        self.url = url\n        self.timeout = timeout\n", "app/a.py": "from app.net import Client\nprint(Client('x'))\n"},
     {"app/net.py": "class Client:\n    def __init__(self, url, timeout=3):\n        self.url = url\n        self.timeout = timeout\n", "app/a.py": "from app.net import Client\nprint(Client('x', timeout=9))\n"}),
    ("unused-option", {"app/net.py": "def fetch(url, *, retries=3):\n    return url * retries\n", "app/a.py": "from app.net import fetch\nprint(fetch('x'))\n"},
     {"app/net.py": "def fetch(url, *, retries=3):\n    return url * retries\n", "app/a.py": "from app.net import fetch\nopts = {}\nprint(fetch('x', **opts))\n"}),
    ("pull-up-method", {"a.py": "class P:\n    def go(self):\n        a = self.x\n        b = a + 1\n        c = b + 2\n        return c\nclass Q:\n    def go(self):\n        a = self.x\n        b = a + 1\n        c = b + 2\n        return c\n"},
     {"a.py": "class P:\n    def go(self):\n        a = self.x\n        b = a + 1\n        c = b + 2\n        return c\nclass Q:\n    def go(self):\n        return 1\n"}),
]
ONE_FILE = [*ONE_FILE, *LARGE_CODEBASE_CASES, *QUALITY_CASES, *RESOURCE_CASES, *JS_CASES, *CONFIG_CASES, *SECRET_CASES]
ONE_FILE += JVMGO_CASES  # team jvmgo
ONE_FILE = [*ONE_FILE, *NATIVE_CASES]  # team native
ONE_FILE = [*ONE_FILE, *CONFIG_TEAM_CASES]  # config team
# team py: Python rules for the blind P0 cases (tests/rule_cases_py.py).
ONE_FILE = [*ONE_FILE, *PY_CASES]
GIT_ONLY = {"test-weakened", "committed-artifact"}  # exercised against a real git repository in test_tools.py
NOTEBOOK_RULES = {"nb-out-of-order", "nb-hidden-state", "nb-unpinned-install", "nb-large-output", "nb-sensitive-output"}


def fired(findings, rule):
    return [f for f in findings if f["rule"] == rule]


def write(root: Path, files: dict) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def scan_repo(tmp_path, files):
    write(tmp_path, files)
    return scan.run_scan(tmp_path, use_cache=False).findings


@pytest.mark.parametrize("rule, path, positive, negative", ONE_FILE, ids=[f"{c[0]}-{i}" for i, c in enumerate(ONE_FILE)])
def test_one_file_rule(rule, path, positive, negative):
    assert fired(scan.scan_text(path, positive), rule), f"{rule} should fire"
    if negative is not None:
        assert not fired(scan.scan_text(path, negative), rule), f"{rule} shouldn't fire on the near miss"


@pytest.mark.parametrize("rule, positive, negative", PROJECT, ids=[f"{c[0]}-{i}" for i, c in enumerate(PROJECT)])
def test_project_rule(rule, positive, negative, tmp_path):
    (tmp_path / "yes").mkdir()
    (tmp_path / "no").mkdir()
    assert fired(scan_repo(tmp_path / "yes", positive), rule), f"{rule} should fire"
    assert not fired(scan_repo(tmp_path / "no", negative), rule), f"{rule} shouldn't fire on the near miss"


def test_every_rule_in_the_catalog_has_a_case():
    covered = {c[0] for c in ONE_FILE} | {c[0] for c in PROJECT} | GIT_ONLY | NOTEBOOK_RULES
    assert not {rule.id for rule in RULES} - covered, "rules with no test"


def test_catalog_is_well_formed():
    assert len(BY_ID) == len(RULES), "duplicate rule id"
    for rule in RULES:
        assert rule.severity in SEVERITIES and rule.confidence in ("high", "medium", "low")
        assert rule.tier in "ABC" and rule.layer in LAYERS and rule.category in CATEGORIES
        assert rule.title and rule.fix


def notebook(cells: list[tuple[str, int | None]], output_size: int = 0, output: str = "") -> str:
    return json.dumps({"cells": [{"cell_type": "code", "execution_count": count, "source": source, "outputs": [{"text": output + "x" * output_size}]} for source, count in cells]})


def test_notebook_rules():
    bad = notebook([("print(df)", 2), ("import pandas as pd\ndf = pd.DataFrame()", 1), ("!pip install pandas", 3)], output_size=600_000, output="a@example.org b@example.org ")
    findings = scan.scan_text("analysis.ipynb", bad)
    for rule in NOTEBOOK_RULES:
        assert fired(findings, rule), rule
    good = notebook([("import pandas as pd\ndf = pd.DataFrame()", 1), ("print(df)", 2), ("!pip install pandas==2.2.0", 3)])
    findings = scan.scan_text("analysis.ipynb", good)
    for rule in NOTEBOOK_RULES:
        assert not fired(findings, rule), rule


def test_notebook_findings_point_at_the_cell():
    findings = scan.scan_text("a.ipynb", notebook([("x = 1", 1), ("def f(a=[]):\n    return a", 2)]))
    default = fired(findings, "mutable-default")[0]
    assert default["cell"] == 2 and default["line"] == 1


def test_inline_suppression_needs_the_right_rule():
    code = "def f(x=[]):  # occam: ignore[mutable-default] shared on purpose\n    return x\n"
    assert not fired(scan.scan_text("a.py", code), "mutable-default")
    assert fired(scan.scan_text("a.py", code.replace("mutable-default", "bare-except")), "mutable-default")


def test_secret_values_are_never_repeated():
    secret = "abc123def456ghi789"
    finding = fired(scan.scan_text("a.py", f'API_KEY = "{secret}"\n'), "hardcoded-secret")[0]
    assert secret not in finding["message"]
    assert secret not in json.dumps({k: v for k, v in finding.items() if k != "evidence"})


def test_generated_files_are_skipped():
    assert not scan.scan_text("gen.py", "# Code generated by protoc. DO NOT EDIT.\ndef f(x=[]):\n    pass\n")


def test_unparseable_python_still_gets_text_rules():
    record = scan.analyze_text("a.py", "def f(:\n    x = 1  # ... rest of the code\n# ... rest of the code\n")
    assert record["parse_error"]
    assert any(f["rule"] == "truncation-marker" for f in record["findings"])


def test_builtins_newer_than_the_running_python_are_defined():
    text = "async def f(xs, errors):\n    first = await anext(aiter(xs))\n    raise ExceptionGroup('x', errors) if errors else BaseExceptionGroup('y', [first])\n"
    assert not fired(scan.analyze_text("app/a.py", text)["findings"], "undefined-name")


def test_a_bare_annotation_in_a_loop_keeps_the_files_findings():
    record = scan.analyze_text("a.py", "import pickle\n\ndef f(xs, data):\n    for i in xs:\n        n: int\n    return pickle.loads(data)\n")
    assert record["parse_error"] is None
    assert fired(record["findings"], "unsafe-deserialize")


@pytest.mark.parametrize("module", ["rules_py_agent", "rules_py_semantics", "rules_py_resources"])
def test_one_rule_module_breaking_loses_only_its_own_findings(module, monkeypatch):
    def broken(*args, **kwargs):
        raise AttributeError("'NoneType' object has no attribute '_fields'")
    monkeypatch.setattr(getattr(rules_py, module), "findings", broken)
    record = scan.analyze_text("a.py", "import pickle\n\ndef f(data):\n    return pickle.loads(data)\n")
    assert record["parse_error"] is None
    assert fired(record["findings"], "unsafe-deserialize")


def test_identity_survives_moving_lines():
    first = fired(scan.scan_text("a.py", "def f(x=[]):\n    return x\n"), "mutable-default")[0]["id"]
    second = fired(scan.scan_text("a.py", "\n\n\ndef f(x=[]):\n    return x\n"), "mutable-default")[0]["id"]
    assert first == second


def test_scanner_never_runs_the_code(tmp_path):
    marker = tmp_path / "ran"
    write(tmp_path, {"evil.py": f"open({str(marker)!r}, 'w').close()\nimport json\njson.nonsense\n", "json.py": f"open({str(marker)!r}, 'w').close()\n"})
    scan.run_scan(tmp_path, use_cache=False)
    assert not marker.exists()


def test_a_local_module_shadowing_stdlib_cant_run_in_the_attribute_probe(tmp_path, monkeypatch):
    marker = tmp_path / "ran"
    write(tmp_path, {"os.py": f"open({str(marker)!r}, 'w').close()\n", "a.py": "import os\nprint(os.path.exist('x'))\n"})
    monkeypatch.chdir(tmp_path)
    scan.run_scan(tmp_path, use_cache=False)
    assert not marker.exists()


def test_state_dir_override_is_respected(tmp_path, monkeypatch):
    from occam_tools.files import state_dir
    monkeypatch.setenv("OCCAM_STATE_DIR", str(tmp_path / "state"))
    # A root holding one folder per repository, so one exported for a CI worker can't merge unrelated repositories' goals and baselines.
    assert state_dir(tmp_path).parent == tmp_path / "state"


@pytest.mark.parametrize("name, text", [
    ("one long word", "x = '" + "a" * 900_000 + "'\n"),
    ("dotted run", "x = '" + "a.b-" * 200_000 + "'\n"),
    ("many quotes", "'\"`" * 200_000 + "\n"),
    ("open parens", "(" * 100_000 + "\n"),
    ("colons in a url shape", "http://" + "a:" * 200_000 + "\n"),
    ("blank lines", "\n" * 300_000),
    ("deep nesting", "[" * 3000 + "]" * 3000 + "\n"),
    ("comment run", "# " + "x " * 300_000 + "\n"),
    ("braces", "function f() {" + "{" * 100_000 + "}" * 100_000 + "}\n"),
    # From a review of rules_js: brackets and tags left open, on short lines so the minified-file skip doesn't apply.
    ("route calls left open", "router.get('/x', (\n" * 15_000),
    ("catches left open", "try {} catch (e) {\n" * 15_000),
    ("async arrows left open", "async x => {\n" * 20_000),
    ("findMany left open", "x.findMany(\n" * 20_000),
    ("tags with braces left open", "<div {\n{<div a}\n" * 15_000),
    # From the third review: nested blocks that do close, so each one spans most of the file.
    ("catches nested and closed", "try {} catch (e) {\n" * 10_000 + "}\n" * 10_000),
    ("routes nested and closed", "router.get('/x', \n" * 10_000 + ")\n" * 10_000),
])
@pytest.mark.parametrize("path", ["a.py", "a.ts", "a.go", "a.sql", "a.sh"])
def test_hostile_input_stays_fast(path, name, text):
    """The scanner reads repositories it can't trust. Input a project chose mustn't be able to stall it."""
    started = time.monotonic()
    scan.scan_text(path, "# short first line\n" + text)
    assert time.monotonic() - started < 20, f"{name} took too long"


def test_huge_notebook_output_stays_fast():
    started = time.monotonic()
    findings = scan.scan_text("a.ipynb", notebook([("x = 1", 1)], output_size=5_000_000))
    assert time.monotonic() - started < 20
    assert fired(findings, "nb-large-output")


def test_blind_fixture_recall_doesnt_regress():
    """A guard on known ground, not a measure of quality: see docs/evaluation.md. The key has been read, so this is development data."""
    sys.path.insert(0, str(ROOT / "evals"))
    import score_audit
    result = score_audit.score_scan(score_audit.scanner_findings(), ("high", "medium"))
    assert int(result["static"].split("/")[0]) >= 28, result
    assert int(result["decoys_flagged"].split("/")[0]) <= 8, result


def test_a_swallowed_exception_with_a_stated_reason_is_a_low_confidence_lead():
    def confidence(comment):
        text = f"try:\n    f()\nexcept Exception:  {comment}\n    pass\n"
        return fired(scan.scan_text("app/a.py", text), "swallowed-exception")[0]["confidence"]
    assert confidence("# noqa: BLE001 one bad session can't stop the lane") == "low"
    assert confidence("# noqa: BLE001") == "medium"
    assert confidence("") == "high"


def test_a_joined_argument_list_is_not_sql():
    assert not fired(scan.scan_text("app/a.py", "def f(client, args):\n    return client.execute(['tmux'] + args)\n"), "sql-injection")
    assert fired(scan.scan_text("app/a.py", "def f(conn, name):\n    return conn.execute('SELECT ' + name)\n"), "sql-injection")


def test_sql_built_from_a_constant_or_in_a_migration_is_not_a_live_injection():
    assert not fired(scan.scan_text("app/a.py", "TABLE = 't'\ndef f(conn):\n    return conn.execute(f'SELECT * FROM {TABLE}')\n"), "sql-injection")
    found = fired(scan.scan_text("db/alembic/versions/1.py", "def f(conn, name):\n    return conn.execute(f'DROP INDEX {name}')\n"), "sql-injection")
    assert found and found[0]["confidence"] == "low"
    assert not fired(scan.scan_text("db/migrations/1.py", "def f(c, ids):\n    for i in ids:\n        c.execute('SELECT 1', (i,))\n"), "query-in-loop")


def test_a_module_python_removed_is_not_an_invented_package(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nrequires-python = "<3.13"\n')
    (tmp_path / "a.py").write_text("import audioop\nprint(audioop)\n")
    assert not fired(scan.run_scan(tmp_path, use_cache=False).findings, "phantom-import")


def test_an_import_used_only_inside_an_f_string_is_used():
    text = 'from html import escape\n\ndef f(url):\n    return f"<a href=\'{escape(url)}\'>"\n'
    assert not fired(scan.scan_text("app/a.py", text), "unused-import")
    assert fired(scan.scan_text("app/a.py", "from html import escape\n\ndef f(url):\n    return f\"{url}\"\n"), "unused-import")


def test_comparing_two_calls_is_not_a_tautology():
    assert not fired(scan.scan_text("tests/test_a.py", "def test_s():\n    assert Ledger.default() is Ledger.default()\n"), "test-tautology")
    assert fired(scan.scan_text("tests/test_a.py", "def test_s():\n    x = 1\n    assert x == x\n"), "test-tautology")


def test_retries_and_written_out_loops_are_not_per_item():
    for retry in ("def f(client, u, n):\n    for attempt in range(n):\n        client.get(u)\n", "def f(client, u, retries):\n    for i in range(retries):\n        client.get(u)\n"):
        assert not fired(scan.scan_text("app/a.py", retry), "query-in-loop")
    per_item = "def f(client, ids):\n    for i in range(len(ids)):\n        client.get(ids[i])\n"
    assert fired(scan.scan_text("app/a.py", per_item), "query-in-loop")
    tables = "def f(c, i):\n    for table in ('a', 'b'):\n        c.execute(f'DELETE FROM {table}')\n"
    assert not fired(scan.scan_text("app/a.py", tables), "sql-injection")
    assert fired(scan.scan_text("app/a.py", "def f(c, tables):\n    for table in tables:\n        c.execute(f'DELETE FROM {table}')\n"), "sql-injection")


def test_a_swallowed_exception_ranks_higher_where_money_or_auth_is_handled(tmp_path):
    body = "def f():\n    try:\n        g()\n    except Exception:\n        pass\n"
    (tmp_path / "cleanup.py").write_text(body)
    (tmp_path / "billing.py").write_text(body)
    severity = {f["path"]: f["severity"] for f in fired(scan.run_scan(tmp_path, use_cache=False).findings, "swallowed-exception")}
    assert severity == {"cleanup.py": "medium", "billing.py": "high"}


def test_pip_freeze_output_is_not_a_list_of_unused_dependencies(tmp_path):
    (tmp_path / "a.py").write_text("print(1)\n")
    (tmp_path / "requirements.txt").write_text("".join(f"package-{i}==1.0\n" for i in range(40)))
    assert not fired(scan.run_scan(tmp_path, use_cache=False).findings, "unused-dependency")
    (tmp_path / "requirements.txt").write_text("flask\n")
    assert fired(scan.run_scan(tmp_path, use_cache=False).findings, "unused-dependency")


def test_asking_people_not_to_edit_something_doesnt_hide_the_file():
    assert scan.scan_text("keys.py", "# Do not edit this list without asking Bob\neval(input())\n")


def _notebook(*cells: str) -> str:
    return json.dumps({"cells": [{"cell_type": "code", "source": cell, "outputs": [], "execution_count": index + 1} for index, cell in enumerate(cells)], "metadata": {}, "nbformat": 4, "nbformat_minor": 5})


def test_a_helper_defined_later_is_fine_when_its_caller_runs_later_still():
    def hidden(*cells: str) -> list:
        return [finding for finding in scan.scan_text("n.ipynb", _notebook(*cells)) if finding["rule"] == "nb-hidden-state"]

    assert not hidden("def f():\n    return helper()\n", "def helper():\n    return 1\n", "f()\n")
    assert not hidden("def f(**kwargs):\n    return kwargs\n", "f(a=1)\n", "kwargs = {}\n")
    assert not hidden("def f(*items, /):\n    return items\n", "f(1)\n", "items = []\n")
    assert hidden("print(total)\n", "total = 1\n")
    assert hidden("def f():\n    return LATER\n\nprint(f())\n", "LATER = 1\n"), "called in its own cell"
    assert hidden("def f():\n    return LATER\n", "f()\n", "LATER = 1\n"), "called before what it reads exists"
    assert hidden("def g():\n    return LATER\n\ndef f():\n    return g()\n\nf()\n", "LATER = 1\n"), "through another function"
    assert hidden("class A:\n    def __init__(self):\n        self.v = LATER\n\nA()\n", "LATER = 1\n"), "through a class"
    assert hidden("class C:\n    def m(self):\n        return LATER\n\nC().m()\n", "LATER = 1\n"), "a method called at once"
    assert hidden("class C:\n    def __init__(self):\n        self.go()\n    def go(self):\n        return LATER\n\nC()\n", "LATER = 1\n"), "a method __init__ calls"
    assert hidden("class C:\n    def __enter__(self):\n        return LATER\n    def __exit__(self, *a):\n        pass\n\nwith C():\n    pass\n", "LATER = 1\n"), "a context manager"
    assert hidden("def f(x):\n    return x\n", "print(x)\n", "x = 1\n"), "a parameter isn't a definition"
    assert not hidden("def f(x):\n    def g():\n        return x\n    return g()\n", "f(1)\n", "x = 3\n"), "a nested function reads its enclosing scope"
    assert not hidden("def setup():\n    global CONFIG\n    CONFIG = 1\n", "setup()\n", "print(CONFIG)\n", "CONFIG = 2\n"), "a function can set a global"
    assert hidden("@memo\ndef f():\n    return 1\n", "memo = print\n"), "a decorator runs at definition"
    assert hidden("def f(x=LIMIT):\n    return x\n", "LIMIT = 1\n"), "a default runs at definition"
    assert hidden("(lambda: LATER)()\n", "LATER = 1\n"), "a lambda is usually called where it's written"


def test_pass_through_names_a_method_on_a_new_object():
    """It printed "forwards to ()" when the callee had no dotted name."""
    found = [f for f in scan.scan_text("a.py", "def is_leap(year):\n    return Calculator().calculate(year)\n") if f["rule"] == "pass-through"]
    assert found and "Calculator().calculate()" in found[0]["message"]


def test_json_glued_with_plus_is_one_finding_per_chain():
    code = "def f(a, b):\n    return '{\"to\": \"' + a + '\", \"s\": \"' + b + '\"}'\n"
    assert len([f for f in scan.scan_text("a.py", code) if f["rule"] == "handrolled-json"]) == 1


# team py: what a fresh review of the Python recall rules found, kept fixed.
def test_a_cycle_of_names_in_a_shell_command_keeps_the_files_other_findings():
    text = "import os\n\n\ndef run(flag):\n    if flag:\n        a = b\n    else:\n        b = a\n    os.system(a)\n    password = 'hunter2hunter2'\n    return password\n"
    rules = {finding["rule"] for finding in scan.scan_text("app/cyc.py", text)}
    assert {"shell-injection", "hardcoded-secret"} <= rules


def test_fail_open_on_a_jwt_fallback_never_sends_the_agent_back_on_its_own():
    text = ("import jwt\ndef claims_for(token, keys):\n    try:\n        return jwt.decode(token, keys.current(), algorithms=['RS256'])\n    except KeyError:\n"
            "        return jwt.decode(token, options={'verify_signature': False})\n")
    found = scan.scan_text("app/auth.py", text)
    fail_open = [finding for finding in found if finding["rule"] == "fail-open"]
    assert fail_open and all(finding["confidence"] == "medium" for finding in fail_open)
    assert {finding["line"] for finding in fail_open}.isdisjoint({finding["line"] for finding in found if finding["rule"] == "jwt-unverified"})


@pytest.mark.parametrize("text", [
    "".join(f"class R{i}(PermissionRequiredMixin, ListView):\n    model = M{i}\n    permission_required = 'x'\n" for i in range(1500))
    + "".join(f"class W{i}(LoginRequiredMixin, CreateView):\n    def post(self, request):\n        return N{i}.objects.create(a=1)\n" for i in range(1500)),
    "def f(x):\n" + "".join(f"    if Thing.objects.filter(a={i}).exists():\n        return {i}\n" for i in range(3000)) + "    Thing.objects.create(a=x)\n",
], ids=["thousands of views", "thousands of existence checks"])
def test_the_recall_rules_stay_linear(text):
    started = time.monotonic()
    scan.scan_text("app/views.py", text)
    assert time.monotonic() - started < 20
# Team js: inputs that made the JavaScript rules quadratic before the third review. Each is timed at two sizes. Four times the input has to
# stay well under sixteen times the time, and under a few seconds outright.
_JS_HOSTILE = {
    "hmac keys": lambda n: "".join(f"const h{i} = crypto.createHmac('sha256', key{i});\n" for i in range(n)),
    "nested retry loops": lambda n: "for (let attempt = 0; attempt < 3; attempt++) {\n" * n + "try { await api.post('/x') } catch (e) {}\n" + "}\n" * n,
    "stream writes": lambda n: "const s = fs.createWriteStream('x');\napp.post('/x', (req, res) => {\n" + "  s.write(x);\n" * n + "  res.json({});\n});\n",
    "method chain": lambda n: "const s = fs.createWriteStream('x');\napp.post('/x', (req, res) => {\n  a" + "\n  .a" * n + ";\n});\n",
    "sibling bindings": lambda n: "".join("{ const a = a + req.body.x; }\n" for _ in range(n)),
    "controller methods": lambda n: "@Controller('x')\nclass A {\n" + "".join(f"  f{i}(a) {{\n    return a;\n  }}\n" for i in range(n)) + "}\n",
    "long signature names": lambda n: "".join("if (" + "Sig" * 300 + " x\n" for _ in range(n // 10)),
    "comparisons": lambda n: "".join("a" * 118 + ",==b;\n" for _ in range(n)),
    "nested functions": lambda n: "function a(cmd) {" * n + "exec(cmd);" + "}" * n,
}


@pytest.mark.parametrize("name", sorted(_JS_HOSTILE))
def test_js_rules_stay_linear_on_hostile_input(name):
    def seconds(size: int) -> float:
        source = load("src/x.ts", _JS_HOSTILE[name](size))
        started = time.perf_counter()
        rules_js.findings(source, False)
        return time.perf_counter() - started

    small, large = seconds(1000), seconds(4000)
    assert large < 8 * small + 0.25 and large < 4, f"{name}: {small:.2f}s at 1000, {large:.2f}s at 4000"

