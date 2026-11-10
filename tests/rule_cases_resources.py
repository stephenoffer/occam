"""Rules in rules_py_resources.py and the config rules added beside them, each as (rule, path, what should fire, its near miss).
test_scanner_rules.py runs them with the rest."""

RESOURCE_CASES = [
 ("mock-assert-typo", "tests/test_a.py", "def test_send(mailer):\n    mailer.send.called_once_with('a@b.c')\n", "def test_send(mailer):\n    mailer.send.assert_called_once_with('a@b.c')\n"),
 ("mock-assert-typo", "tests/test_a.py", "def test_send(m):\n    assert m.has_calls([call(1)])\n", "def test_send(m):\n    assert m.called\n"),
 ("lazy-after-close", "app/a.py", "def rows(path):\n    with open(path) as f:\n        return (line.strip() for line in f)\n", "def rows(path):\n    with open(path) as f:\n        return [line.strip() for line in f]\n"),
 ("lazy-after-close", "app/a.py", "import csv\ndef rows(path):\n    with open(path) as f:\n        return csv.reader(f)\n", "import csv\ndef rows(path):\n    with open(path) as f:\n        yield from csv.reader(f)\n"),
 ("lazy-after-close", "app/a.py", "def names(path):\n    with open(path) as f:\n        return map(str.strip, f)\n", "def names(path, items):\n    with open(path) as f:\n        header = f.readline()\n    return map(str.strip, items)\n"),
 ("await-under-thread-lock", "app/a.py", "async def bump(self):\n    with self._lock:\n        await self.store.save()\n", "async def bump(self):\n    async with self._lock:\n        await self.store.save()\n"),
 ("lock-order", "app/a.py", "def a():\n    with accounts_lock:\n        with ledger_lock:\n            move()\ndef b():\n    with ledger_lock:\n        with accounts_lock:\n            move()\n",
  "def a():\n    with accounts_lock:\n        with ledger_lock:\n            move()\ndef b():\n    with accounts_lock:\n        with ledger_lock:\n            undo()\n"),
 ("cache-reads-user", "app/a.py", "from functools import lru_cache\n@lru_cache\ndef dashboard():\n    return build(current_user.id)\n", "from functools import lru_cache\n@lru_cache\ndef dashboard(user_id):\n    return build(user_id)\n"),
 ("cache-reads-user", "app/a.py", "import functools\n@functools.cache\ndef visible(project):\n    return project.allowed(request.user)\n", "import functools\n@functools.cache\ndef visible(project, user):\n    return project.allowed(user)\n"),
 ("client-per-call", "app/a.py", "import requests\ndef fetch(urls):\n    for url in urls:\n        s = requests.Session()\n        yield s.get(url, timeout=5)\n", "import requests\ndef fetch(urls):\n    s = requests.Session()\n    for url in urls:\n        yield s.get(url, timeout=5)\n"),
 ("client-per-call", "app/a.py", "from sqlalchemy import create_engine\n@app.get('/items')\ndef items():\n    engine = create_engine(URL)\n    return engine.execute(Q)\n", "from sqlalchemy import create_engine\nengine = create_engine(URL)\n@app.get('/items')\ndef items():\n    return engine.execute(Q)\n"),
 # A worker reconnecting in a while loop is how it recovers, not a pool per item.
 ("client-per-call", "app/a.py", "import psycopg2\nfor job in jobs:\n    conn = psycopg2.connect(DSN)\n    run(conn, job)\n", "import psycopg2\nwhile True:\n    try:\n        conn = psycopg2.connect(DSN)\n        serve(conn)\n    except OSError:\n        sleep(1)\n"),
 ("io-in-property", "app/a.py", "import requests\nclass User:\n    @property\n    def avatar(self):\n        return requests.get(self.url, timeout=5).content\n", "import requests\nclass User:\n    def fetch_avatar(self):\n        return requests.get(self.url, timeout=5).content\n"),
 ("io-in-property", "app/a.py", "class Job:\n    @property\n    def rows(self):\n        return self.db.execute(Q).fetchall()\n", "class Job:\n    @property\n    def label(self):\n        return self.name.title()\n"),
 ("unbounded-queue", "app/a.py", "import queue\nq = queue.Queue()\ndef read(sock):\n    while True:\n        q.put(sock.recv(4096))\n", "import queue\nq = queue.Queue(maxsize=1000)\ndef read(sock):\n    while True:\n        q.put(sock.recv(4096))\n"),
 # From the review: the queue docs' worker example fills it from a fixed input, and a crawl feeds its own queue, where a maxsize would deadlock.
 ("unbounded-queue", "app/a.py", "import queue\nq = queue.Queue()\nwhile True:\n    q.put(next_event())\n", "import queue\nq = queue.Queue()\nfor item in range(30):\n    q.put(item)\nwhile True:\n    url = q.get()\n    for link in links(url):\n        q.put_nowait(link)\n"),
 ("nonatomic-state-write", "app/a.py", "import json\nSTATE = 'state.json'\ndef load():\n    with open(STATE) as f:\n        return json.load(f)\ndef save(state):\n    with open(STATE, 'w') as f:\n        json.dump(state, f)\n",
  "import json, os\nSTATE = 'state.json'\ndef load():\n    with open(STATE) as f:\n        return json.load(f)\ndef save(state):\n    with open(STATE + '.tmp', 'w') as f:\n        json.dump(state, f)\n    os.replace(STATE + '.tmp', STATE)\n"),
 ("nonatomic-state-write", "app/a.py", "def bump(self):\n    n = int(self.counter.read_text())\n    self.counter.write_text(str(n + 1))\n", "def report(self, n):\n    self.out.write_text(str(n))\n"),
 # self-review: a device file isn't stored state, as a Cygwin clipboard copy and paste
 ("nonatomic-state-write", "app/a.py", "def copy(text):\n    with open('state.txt', 'wt') as f:\n        f.write(text)\ndef paste():\n    with open('state.txt', 'rt') as f:\n        return f.read()\n",
  "def copy(text):\n    with open('/dev/clipboard', 'wt') as f:\n        f.write(text)\ndef paste():\n    with open('/dev/clipboard', 'rt') as f:\n        return f.read()\n"),
 ("network-in-unit-test", "tests/test_a.py", "import requests\ndef test_price():\n    assert requests.get('https://api.stripe.com/v1/prices', timeout=5).ok\n", "import requests, responses\n@responses.activate\ndef test_price():\n    responses.get('https://api.stripe.com/v1/prices', json={})\n    assert requests.get('https://api.stripe.com/v1/prices', timeout=5).ok\n"),
 ("network-in-unit-test", "tests/test_a.py", "import httpx\ndef test_up():\n    assert httpx.get('https://status.example-corp.io/health').status_code == 200\n", "import httpx\ndef test_up(server):\n    assert httpx.get('http://localhost:8000/health').status_code == 200\n"),
 ("fixed-test-resource", "tests/test_a.py", "import socket\ndef test_listen():\n    s = socket.socket()\n    s.bind(('127.0.0.1', 8080))\n", "import socket\ndef test_listen():\n    s = socket.socket()\n    s.bind(('127.0.0.1', 0))\n"),
 ("fixed-test-resource", "tests/test_a.py", "def test_export():\n    export(open('/tmp/out.csv', 'w'))\n", "def test_export(tmp_path):\n    export(open(tmp_path / 'out.csv', 'w'))\n"),
 # A client naming the port it connects to collides with nothing.
 ("fixed-test-resource", "tests/test_a.py", "def test_app():\n    app.run(port=5000)\n", "def test_db():\n    connect(host='localhost', port=5432)\n"),
 ("unseeded-random-test", "tests/test_a.py", "import random\ndef test_sort():\n    xs = [random.randint(0, 9) for _ in range(50)]\n    assert sort(xs) == sorted(xs)\n", "import random\nrandom.seed(1)\ndef test_sort():\n    xs = [random.randint(0, 9) for _ in range(50)]\n    assert sort(xs) == sorted(xs)\n"),
 ("dense-comprehension", "app/a.py", "cells = [c.value for sheet in book for row in sheet if row for c in row if c]\n", "cells = [c.value for row in sheet for c in row if c]\n"),
 ("dense-comprehension", "app/a.py", "size = 'S' if n < 10 else 'M' if n < 100 else 'L' if n < 1000 else 'XL'\n", "size = 'S' if n < 10 else 'M' if n < 100 else 'L'\n"),
 ("range-len-loop", "app/a.py", "def total(prices):\n    t = 0\n    for i in range(len(prices)):\n        t += prices[i]\n    return t\n", "def scale(prices):\n    for i in range(len(prices)):\n        prices[i] = prices[i] * 2\n"),
 # review of the self-review fixes: outside __iter__, `for x in self` is fine
 ("range-len-loop", "app/a.py", "class Bag(list):\n    def total(self):\n        t = 0\n        for i in range(len(self)):\n            t += self[i]\n        return t\n", "def f(rows):\n    return [i for i in range(3)]\n"),
 # self-review: inside __iter__, `for item in self` would call __iter__ again
 ("range-len-loop", "app/a.py", "def show(rows):\n    for i in range(len(rows)):\n        print(rows[i])\n", "class Masked:\n    def __iter__(self):\n        for i in range(len(self)):\n            yield self[i]\n"),
 ("dropped-task", "app/a.py", "def run(pool, jobs):\n    for job in jobs:\n        pool.submit(work, job)\n", "def run(pool, jobs):\n    futures = [pool.submit(work, job) for job in jobs]\n    return [f.result() for f in futures]\n"),
 ("dropped-task", "app/a.py", "import threading\ndef start():\n    threading.Thread(target=loop).start()\n", "import threading\ndef start():\n    threading.Thread(target=serve_forever, daemon=True).start()\n"),
 ("query-in-loop", "app/models.py", "class Order(models.Model):\n    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)\ndef names():\n    return [o.customer.name for o in Order.objects.all()]\n",
  "class Order(models.Model):\n    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)\ndef names():\n    return [o.customer.name for o in Order.objects.select_related('customer')]\n"),
 # From the review: a field's own attributes, such as an image's url or a date's year, need no query.
 ("query-in-loop", "app/models.py", "class Order(models.Model):\n    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)\nfor order in Order.objects.filter(paid=True):\n    send(order.customer.email)\n",
  "class Order(models.Model):\n    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)\nyears = {o.created_at.year for o in Order.objects.all()}\nurls = [p.image.url for p in Product.objects.filter(active=True)]\n"),
 # From the review: what each rule must leave alone.
 ("lazy-after-close", "app/a.py", "def rows(path):\n    with open(path) as f:\n        return (line for line in f)\n", "import json\ndef rows(path):\n    with open(path) as f:\n        return map(int, f.read().split())\ndef more(path):\n    with open(path) as f:\n        return (l.strip() for l in f.readlines())\ndef items(path):\n    with open(path) as f:\n        return enumerate(json.load(f))\n"),
 ("client-per-call", "app/a.py", "import requests\nfor url in urls:\n    with requests.Session() as s:\n        s.get(url, timeout=5)\n", "import boto3\nfrom sqlalchemy import create_engine\nfor region in regions:\n    ec2 = boto3.client('ec2', region_name=region)\nfor url in urls:\n    engine = create_engine(url)\n    upgrade(engine)\n"),
 ("nonatomic-state-write", "app/a.py", "class Store:\n    def load(self):\n        return self.path.read_text()\n    def save(self, text):\n        self.path.write_text(text)\n", "def read_rows(path):\n    with open(path) as f:\n        return f.read()\ndef write_report(path, rows):\n    with open(path, 'w') as f:\n        f.write(rows)\n"),
 ("network-in-unit-test", "tests/test_a.py", "import requests\ndef test_up():\n    assert requests.get('https://api.example-corp.io/up', timeout=5).ok\n", "import httpx\ndef test_get(httpx_mock):\n    httpx_mock.add_response(json={})\n    assert httpx.get('https://api.example-corp.io/up').status_code == 200\n"),
 ("network-in-unit-test", "tests/test_a.py", "import requests\ndef test_up():\n    assert requests.get('https://api.example-corp.io/up', timeout=5).ok\n", "import pytest, requests\n@pytest.mark.integration\ndef test_up():\n    assert requests.get('https://api.example-corp.io/up', timeout=5).ok\n"),
 ("fixed-test-resource", "tests/test_a.py", "from pathlib import Path\ndef test_save():\n    Path('/tmp/out.json').write_text('{}')\n", "import pytest\nfrom pathlib import Path\ndef test_missing():\n    with pytest.raises(FileNotFoundError):\n        load(Path('/tmp/definitely-missing.json'))\n"),
 ("lock-order", "app/a.py", "class A:\n    def f(self):\n        with self._lock:\n            with self.state_lock:\n                go()\n    def g(self):\n        with self.state_lock:\n            with self._lock:\n                go()\n",
  "class A:\n    def f(self):\n        with self._lock:\n            with self.state_lock:\n                go()\nclass B:\n    def g(self):\n        with self.state_lock:\n            with self._lock:\n                go()\n"),
]
RESOURCE_CASES += [
 # From occam-97's review of the committed rules.
 ("client-per-call", "app/a.py", "import requests\nfor url in urls:\n    s = requests.Session()\n    s.get(url, timeout=5)\n",
  "import psycopg2\nfrom sqlalchemy import create_engine\nfor attempt in range(5):\n    conn = psycopg2.connect(DSN)\nfor tenant in tenants:\n    url = tenant_url(tenant)\n    engine = create_engine(url)\n"),
 ("unbounded-queue", "app/a.py", "import queue\nq = queue.Queue()\nwhile True:\n    q.put(read_sensor())\n", "import queue\nq = queue.Queue()\nwhile True:\n    url = q.get()\n    for link in links(url):\n        q.put(link)\n"),
 ("await-under-thread-lock", "app/a.py", "async def f(self):\n    with self._lock:\n        await self.flush()\n", "def f(self):\n    with self._lock:\n        async def later():\n            await self.flush()\n        self.pending.append(later)\n"),
 ("nonatomic-state-write", "app/a.py", "class Store:\n    def load(self):\n        return self.path.read_text()\n    def save(self, text):\n        self.path.write_text(text)\n",
  "class Reader:\n    def load(self):\n        return self.path.read_text()\nclass Writer:\n    def save(self, text):\n        self.path.write_text(text)\n"),
]
RESOURCE_CASES += [
 # From the third review: range(len(...)) is over items, and an annotated assignment carries the loop's value too.
 ("client-per-call", "app/a.py", "import requests\nfor i in range(len(urls)):\n    s = requests.Session()\n    s.get(urls[i], timeout=5)\n",
  "import boto3\nfor r in regions:\n    name: str = r.upper()\n    ec2 = boto3.client('ec2', region_name=name)\n"),
]

CONFIG_CASES = [
 ("formatter-conflict", "pyproject.toml", "[tool.black]\nline-length = 100\n\n[tool.ruff]\nline-length = 88\n\n[tool.ruff.format]\nquote-style = \"double\"\n", "[tool.black]\nline-length = 88\n\n[tool.ruff]\nline-length = 120\n"),
 ("formatter-conflict", "pyproject.toml", "[tool.black]\nline-length = 88\n\n[tool.isort]\nline_length = 88\n", "[tool.black]\nline-length = 88\n\n[tool.isort]\nmulti_line_output = 3\ninclude_trailing_comma = true\n"),
]

FAKE_KEY = "AKIA" + "A" * 16  # built here so no credential shape sits in the repository
SECRET_CASES = [
 ("live-credential-in-test", "tests/test_jwt.py", f"KEY = '{FAKE_KEY}'\n", "PRIVATE = '-----BEGIN RSA " + "PRIVATE KEY-----\\nMIIEowIBAAKCAQEAu1SU1LfVLPHCozMxH2Mo4lgOEePzNm0tRgeLezV6ffAt0gun\\n-----END RSA " + "PRIVATE KEY-----'\n"),
 ("live-credential-in-test", "tests/test_upload.py", f"def test_upload(s3):\n    s3.login('{FAKE_KEY}')\n", "def test_upload(s3):\n    s3.login('AKIA-test-key')\n"),
 # From the sweep: SkyPilot's tests hold eight URLs like this, all fakes.
 ("live-credential-in-test", "tests/test_upload.py", f"def test_upload(s3):\n    s3.login('{FAKE_KEY}')\n", "def test_proxy(check):\n    check('http://user:" + "sup3rsecret" + "@env.example.com')\n"),
]
