"""Rules added for docs/quality-catalog.md, each as (rule, path, what should fire, its near miss). test_scanner_rules.py runs them with the rest.

Near misses marked "review" are false positives a fresh review found on a first version, so each stays fixed.
"""

QUALITY_CASES = [
 ("loop-variable-closure", "app/a.py", "def f(items):\n    out = []\n    for i in items:\n        out.append(lambda: i)\n    return out\n", "def f(items):\n    out = []\n    for i in items:\n        out.append(lambda i=i: i)\n    return out\n"),
 ("loop-variable-closure", "app/a.py", "for name in names:\n    Button(root, command=lambda: pick(name))\n", "for name in names:\n    rows = sorted(rows, key=lambda r: r[name])\n"),
 ("loop-variable-closure", "app/a.py", "handlers = [lambda: i for i in range(3)]\n", "handlers = [lambda i=i: i for i in range(3)]\n"),
 ("loop-variable-closure", "app/a.py", "for job in jobs:\n    def run():\n        return job.go()\n    callbacks.append(run)\n", "for job in jobs:\n    def run(job=job):\n        return job.go()\n    callbacks.append(run)\n"),
 ("loop-variable-closure", "app/a.py", "for k in keys:\n    table[k] = lambda: k\n", "for k in keys:\n    table[k] = make(k)\n"),
 # review: func= is called straight away by apply
 ("loop-variable-closure", "app/a.py", "for c in cols:\n    hooks.register(lambda: c)\n", "for c in cols:\n    df[c] = df.apply(func=lambda r: r[c] * 2, axis=1)\n"),
 ("mutated-while-iterating", "app/a.py", "def f(items):\n    for x in items:\n        if x < 0:\n            items.remove(x)\n", "def f(items):\n    for x in list(items):\n        if x < 0:\n            items.remove(x)\n"),
 ("mutated-while-iterating", "app/a.py", "def f(d):\n    for k in d:\n        if not d[k]:\n            del d[k]\n", "def f(d):\n    for k in list(d):\n        if not d[k]:\n            del d[k]\n"),
 ("mutated-while-iterating", "app/a.py", "for x in items:\n    if x == target:\n        items.remove(x)\n        log(x)\n", "for x in items:\n    if x == target:\n        items.remove(x)\n        break\n"),
 ("mutated-while-iterating", "app/a.py", "for k, v in d.items():\n    d.pop(k)\n", "for node in queue:\n    queue.append(node.child)\n"),
 ("mutated-while-iterating", "app/a.py", "for t in self.tasks:\n    if t.done:\n        self.tasks.remove(t)\n", "for t in self.tasks:\n    if t.done:\n        self.finished.remove(t)\n"),
 # Found in the standard library: CookieJar walks itself, and its clear() has its own rules.
 ("mutated-while-iterating", "app/a.py", "for c in self.cookies:\n    if c.discard:\n        self.cookies.clear()\n", "for c in self:\n    if c.discard:\n        self.clear(c.domain)\n"),
 # Found in pandas: the break that ends the loop sits one block out from the change.
 ("mutated-while-iterating", "app/a.py", "for f in formats:\n    for x in rows:\n        if x:\n            formats.pop(0)\n        break\n", "for f in formats:\n    try:\n        if ok(f):\n            formats.pop(0)\n            formats.insert(0, f)\n        break\n    except ValueError:\n        pass\n"),
 # Found on SkyPilot: a dict changed while its items() are walked.
 ("mutated-while-iterating", "app/a.py", "def restore(new, old, keys):\n    for key, value in new.items():\n        if key in keys and key not in old:\n            del new[key]\n", "def restore(new, old, keys):\n    for key, value in list(new.items()):\n        if key in keys and key not in old:\n            del new[key]\n"),
 # review: a lambda in the loop runs later, after the loop
 ("mutated-while-iterating", "app/a.py", "for t in tasks:\n    tasks.discard(t)\n", "for t in tasks:\n    t.add_done_callback(lambda f: tasks.discard(f))\n"),
 ("shared-class-mutable", "app/a.py", "class Cart:\n    items = []\n    def add(self, x):\n        self.items.append(x)\n", "class Cart:\n    items = []\n    def __init__(self):\n        self.items = []\n    def add(self, x):\n        self.items.append(x)\n"),
 ("shared-class-mutable", "app/a.py", "class Cache:\n    store = {}\n    def put(self, k, v):\n        self.store[k] = v\n", "class Registry:\n    store = {}\n    @classmethod\n    def put(cls, k, v):\n        cls.store[k] = v\n"),
 ("swallowed-cancellation", "app/a.py", "import asyncio\nasync def worker():\n    try:\n        await work()\n    except asyncio.CancelledError:\n        log('stopped')\n", "import asyncio\nasync def worker():\n    try:\n        await work()\n    except asyncio.CancelledError:\n        log('stopped')\n        raise\n"),
 ("swallowed-cancellation", "app/a.py", "import asyncio\nasync def stop(task):\n    try:\n        await task\n    except asyncio.CancelledError:\n        pass\n", "import asyncio\nasync def stop(task):\n    task.cancel()\n    try:\n        await task\n    except asyncio.CancelledError:\n        pass\n"),
 ("swallowed-cancellation", "app/a.py", "async def run():\n    try:\n        await go()\n    except BaseException:\n        cleanup()\n", "async def run():\n    try:\n        await go()\n    except Exception:\n        cleanup()\n"),
 ("swallowed-cancellation", "app/a.py", "import asyncio\nasync def daemon():\n    while True:\n        try:\n            await tick()\n        except asyncio.CancelledError:\n            break\n", "import asyncio\nasync def daemon():\n    try:\n        await tick()\n    except asyncio.CancelledError:\n        asyncio.current_task().uncancel()\n"),
 # review: a concurrent.futures result in synchronous code, and waiting through wait_for on a task this code cancelled
 ("swallowed-cancellation", "app/a.py", "async def poll(f):\n    try:\n        await f\n    except CancelledError:\n        pass\n", "from concurrent.futures import CancelledError\ndef poll(f):\n    try:\n        return f.result()\n    except CancelledError:\n        pass\n"),
 ("swallowed-cancellation", "app/a.py", "import asyncio\nasync def stop(task):\n    try:\n        await asyncio.wait_for(task, 5)\n    except asyncio.CancelledError:\n        pass\n", "import asyncio\nasync def stop(task):\n    task.cancel()\n    try:\n        await asyncio.wait_for(task, 5)\n    except asyncio.CancelledError:\n        pass\n"),
 # review2: the usual shutdown cancels each task, then gathers them; and the exception kept to raise after cleanup
 ("swallowed-cancellation", "app/a.py", "import asyncio\nasync def wait_all(tasks):\n    try:\n        await asyncio.gather(*tasks)\n    except asyncio.CancelledError:\n        pass\n", "import asyncio\nasync def stop(tasks):\n    for t in tasks:\n        t.cancel()\n    try:\n        await asyncio.gather(*tasks)\n    except asyncio.CancelledError:\n        pass\n"),
 ("swallowed-cancellation", "app/a.py", "import asyncio\nasync def worker(q):\n    while True:\n        try:\n            await q.get()\n        except asyncio.CancelledError:\n            continue\n", "import asyncio\nasync def run(self):\n    err = None\n    try:\n        await self.step()\n    except asyncio.CancelledError as e:\n        err = e\n    await self.close()\n    if err:\n        raise err\n"),
 # review3: logging the exception isn't keeping it, and cancelling a different task doesn't excuse swallowing this one
 ("swallowed-cancellation", "app/a.py", "import asyncio\nasync def loop(log):\n    while True:\n        try:\n            await tick()\n        except asyncio.CancelledError as e:\n            log.info('cancelled %s', e)\n", "import asyncio\nasync def loop(log):\n    while True:\n        try:\n            await tick()\n        except asyncio.CancelledError as e:\n            log.info('cancelled %s', e)\n            raise\n"),
 ("swallowed-cancellation", "app/a.py", "import asyncio\nasync def serve(self):\n    try:\n        await self.work()\n    except asyncio.CancelledError:\n        pass\n    finally:\n        self._heartbeat.cancel()\n", "import asyncio\nasync def serve(self):\n    try:\n        await self.work()\n    except asyncio.CancelledError:\n        raise\n    finally:\n        self._heartbeat.cancel()\n"),
 # third review: a list holding the exception keeps it
 ("swallowed-cancellation", "app/a.py", "import asyncio\nasync def w(failures):\n    while True:\n        try:\n            await tick()\n        except asyncio.CancelledError as e:\n            failures.append(str(e))\n", "import asyncio\nasync def w(ts, failures):\n    for t in ts:\n        try:\n            await t\n        except asyncio.CancelledError as exc:\n            failures.append([t, exc])\n    if failures:\n        raise failures[0][1]\n"),
 # second review: keeping only the text of the exception isn't keeping it
 ("swallowed-cancellation", "app/a.py", "import asyncio\nasync def w(self):\n    while True:\n        try:\n            await tick()\n        except asyncio.CancelledError as e:\n            self.note = f'cancelled: {e}'\n", "import asyncio\nasync def w(self):\n    try:\n        await tick()\n    except asyncio.CancelledError as e:\n        self.error = e\n    await self.close()\n    if self.error:\n        raise self.error\n"),
 # self-review: errors collected to raise after cleanup are kept, as aiohttp's cleanup does
 ("swallowed-cancellation", "app/a.py", "import asyncio\nasync def cleanup(its, log):\n    for it in its:\n        try:\n            await it.close()\n        except asyncio.CancelledError as exc:\n            log.append(f'cancelled: {exc}')\n", "import asyncio\nasync def cleanup(its):\n    errors = []\n    for it in its:\n        try:\n            await it.close()\n        except (Exception, asyncio.CancelledError) as exc:\n            errors.append(exc)\n    if errors:\n        raise errors[0]\n"),
 ("salted-hash-partition", "app/a.py", "def shard(key, n):\n    return hash(key) % n\n", "import zlib\ndef shard(key, n):\n    return zlib.crc32(key.encode()) % n\n"),
 # review: & (n - 1) is the usual power-of-two bucket, and hash() of an int is the int
 ("salted-hash-partition", "app/a.py", "def shard(user, n):\n    return hash(user.email) & (n - 1)\n", "def shard(rid, n):\n    return hash(uuid.UUID(rid).int) % n\n"),
 ("wall-clock-wait", "app/a.py", "import time\ndef wait(ready, timeout):\n    deadline = time.time() + timeout\n    while time.time() < deadline:\n        if ready():\n            return True\n    return False\n", "import time\ndef wait(ready, timeout):\n    deadline = time.monotonic() + timeout\n    while time.monotonic() < deadline:\n        if ready():\n            return True\n    return False\n"),
 # review2: striping a structure in this process, and hashing an object
 ("salted-hash-partition", "app/a.py", "def node_for(key, nodes):\n    return nodes[hash(key) % NUM_SHARDS]\n", "class Striped:\n    def lock_for(self, key):\n        return self.locks[hash(key) % len(self.locks)]\n"),
 ("salted-hash-partition", "app/a.py", "def tag(key):\n    return hash(key) & 0xFF\n", "class Node:\n    def tag(self):\n        return hash(self) & 0xFF\n"),
 # review3: a length of servers or shards is the bug itself, not in-process striping
 ("salted-hash-partition", "app/a.py", "def node_for(key, nodes):\n    return nodes[hash(key) % len(nodes)]\n", "def node_for(key, nodes):\n    return nodes[zlib.crc32(key.encode()) % len(nodes)]\n"),
 ("wall-clock-wait", "app/a.py", "import time\ndef poll(ready, timeout):\n    start = time.time()\n    while True:\n        if time.time() - start > timeout:\n            return False\n        if ready():\n            return True\n", "import time\ndef run_at(job, when):\n    while time.time() < when:\n        time.sleep(1)\n    job()\n"),
 ("stdlib-shadowed", "random.py", "def pick():\n    return 4\n", None),
 ("stdlib-shadowed", "scripts/json.py", "def load():\n    return {}\n", None),
 ("unwrapped-decorator", "app/a.py", "def logged(fn):\n    def wrapper(*args, **kwargs):\n        return fn(*args, **kwargs)\n    return wrapper\n", "import functools\ndef logged(fn):\n    @functools.wraps(fn)\n    def wrapper(*args, **kwargs):\n        return fn(*args, **kwargs)\n    return wrapper\n"),
 ("gpu-timing-unsynced", "app/bench.py", "import time\nimport torch\ndef bench(model, x):\n    x = x.cuda()\n    start = time.perf_counter()\n    model(x)\n    return time.perf_counter() - start\n", "import time\nimport torch\ndef bench(model, x):\n    x = x.cuda()\n    torch.cuda.synchronize()\n    start = time.perf_counter()\n    model(x)\n    torch.cuda.synchronize()\n    return time.perf_counter() - start\n"),
 # Found on SkyPilot: two time.time() reads in a GPU file that only stamp a record.
 ("gpu-timing-unsynced", "app/train.py", "import time\nimport torch\ndef step(model, x):\n    t0 = time.time()\n    loss = model(x.cuda())\n    t1 = time.time()\n    return t1 - t0\n", "import time\nimport torch\ndef save(model, epoch):\n    torch.save(model, 'm.pt')\n    meta = {'start': time.time(), 'model': model(epoch)}\n    meta['end'] = time.time()\n    return meta\n"),
 ("nan-comparison", "app/a.py", "import math\ndef clean(x):\n    return None if x == math.nan else x\n", "import math\ndef clean(x):\n    return None if math.isnan(x) else x\n"),
 ("nan-comparison", "app/a.py", "import numpy as np\nmask = values != np.nan\n", "import numpy as np\nmask = ~np.isnan(values)\n"),
 ("nested-event-loop", "app/a.py", "import asyncio\nasync def handler():\n    return asyncio.run(fetch())\n", "import asyncio\nasync def handler():\n    return await fetch()\ndef main():\n    asyncio.run(handler())\n"),
 ("process-pool-unpicklable", "app/a.py", "from concurrent.futures import ProcessPoolExecutor\ndef run(xs):\n    with ProcessPoolExecutor() as pool:\n        return list(pool.map(lambda x: x * 2, xs))\n", "from concurrent.futures import ThreadPoolExecutor\ndef run(xs):\n    with ThreadPoolExecutor() as pool:\n        return list(pool.map(lambda x: x * 2, xs))\n"),
 ("process-pool-unpicklable", "app/a.py", "import multiprocessing\ndef run(xs):\n    def double(x):\n        return x * 2\n    pool = multiprocessing.Pool(4)\n    return pool.map(double, xs)\n", "import multiprocessing\ndef double(x):\n    return x * 2\ndef run(xs):\n    pool = multiprocessing.Pool(4)\n    return pool.map(double, xs)\n"),
 # Found in tbb: its own Pool is a thread pool. review: multiprocess and loky pickle with dill and cloudpickle, which take lambdas
 ("process-pool-unpicklable", "app/a.py", "from multiprocessing import Pool\ndef run(xs):\n    pool = Pool(4)\n    return pool.map(lambda x: x, xs)\n", "from tbb.pool import Pool\ndef run(xs):\n    pool = Pool(4)\n    return pool.map(lambda x: x, xs)\n"),
 ("process-pool-unpicklable", "app/a.py", "import multiprocessing as mp\ndef run(xs):\n    with mp.Pool(4) as pool:\n        return pool.map(lambda x: x, xs)\n", "import multiprocess as mp\ndef run(xs):\n    with mp.Pool(4) as pool:\n        return pool.map(lambda x: x, xs)\n"),
 ("process-pool-unpicklable", "app/a.py", "import concurrent.futures\ndef run(xs):\n    with concurrent.futures.ProcessPoolExecutor() as pool:\n        return list(pool.map(lambda x: x, xs))\n", "import loky\ndef run(xs):\n    with loky.ProcessPoolExecutor() as pool:\n        return list(pool.map(lambda x: x, xs))\n"),
 ("compile-in-loop", "app/a.py", "import numba\ndef run(f, batches):\n    for batch in batches:\n        fast = numba.njit(f)\n        fast(batch)\n", "import numba\ndef run(f, batches):\n    fast = numba.njit(f)\n    for batch in batches:\n        fast(batch)\n"),
 # review2: JAX caches compilation by function, so a fresh jax.jit wrapper needn't recompile
 ("compile-in-loop", "app/b.py", "import tensorflow as tf\nfor batch in batches:\n    step = tf.function(train_step)\n    step(batch)\n", "import jax\nfor batch in batches:\n    step = jax.jit(train_step)\n    step(batch)\n"),
 ("ctypes-untyped", "app/a.py", "import ctypes\nlib = ctypes.CDLL('libfoo.so')\ndef size(p):\n    return lib.buffer_size(p)\n", "import ctypes\nlib = ctypes.CDLL('libfoo.so')\nlib.buffer_size.argtypes = [ctypes.c_void_p]\nlib.buffer_size.restype = ctypes.c_size_t\ndef size(p):\n    return lib.buffer_size(p)\n"),
 # Found in tbb: a call that takes nothing and returns nothing used.
 ("ctypes-untyped", "app/a.py", "import ctypes\nlib = ctypes.CDLL('x.so')\nhandle = lib.open_handle()\n", "import ctypes\nlib = ctypes.CDLL('x.so')\nlib.release_resources()\n"),
 # review: types declared through getattr can't be matched by name, so the library is left alone
 ("ctypes-untyped", "app/a.py", "import ctypes\nlib = ctypes.CDLL('x.so')\nn = lib.count(p)\n", "import ctypes\nlib = ctypes.CDLL('x.so')\nfor name in NAMES:\n    getattr(lib, name).restype = ctypes.c_size_t\nn = lib.count(p)\n"),
 ("check-then-insert", "app/a.py", "def subscribe(email):\n    if not Subscriber.objects.filter(email=email).exists():\n        Subscriber.objects.create(email=email)\n", "def subscribe(email):\n    Subscriber.objects.get_or_create(email=email)\n"),
 ("check-then-insert", "app/a.py", "def add_tag(session, name):\n    if session.query(Tag).filter_by(name=name).first() is None:\n        session.add(Tag(name=name))\n", "def show_tag(session, name):\n    if session.query(Tag).filter_by(name=name).first() is None:\n        raise NotFound(name)\n"),
 # Found on SkyPilot and s3transfer: a dict lookup and a set add aren't a database race. review: nor is collecting the missing ids.
 ("check-then-insert", "app/a.py", "def ensure(db, key):\n    if db.query(Key).filter_by(key=key).count() == 0:\n        db.add(Key(key=key))\n", "def collect(rules, ports):\n    for rule in rules:\n        if rule.get('port') is None:\n            ports.add(rule['default'])\n"),
 ("check-then-insert", "app/a.py", "def ensure(coll, k):\n    if coll.find_one({'k': k}) is None:\n        coll.insert_one({'k': k})\n", "def missing(ids):\n    out = set()\n    for i in ids:\n        if not Item.objects.filter(pk=i).exists():\n            out.add(i)\n    return out\n"),
 ("retry-not-idempotent", "app/a.py", "from tenacity import retry\n@retry\ndef pay(order):\n    return stripe.Charge.create(amount=order.total)\n", "from tenacity import retry\n@retry\ndef pay(order):\n    return stripe.Charge.create(amount=order.total, idempotency_key=order.id)\n"),
 # review: a model call and a GraphQL read repeat harmlessly
 ("retry-not-idempotent", "app/a.py", "import backoff\n@backoff.on_exception(backoff.expo, Exception)\ndef notify(client, msg):\n    client.send_message(msg)\n", "from tenacity import retry\n@retry(stop=stop_after_attempt(3))\ndef ask(client, **kwargs):\n    return client.chat.completions.create(**kwargs)\n"),
 ("webhook-unverified", "app/a.py", "@app.post('/webhooks/stripe')\ndef stripe_hook():\n    event = request.get_json()\n    mark_paid(event['data'])\n", "@app.post('/webhooks/stripe')\ndef stripe_hook():\n    event = stripe.Webhook.construct_event(request.data, request.headers['Stripe-Signature'], SECRET)\n    mark_paid(event['data'])\n"),
 # review: an authenticated GET that lists webhook settings receives nothing
 ("webhook-unverified", "app/a.py", "@app.route('/hooks/webhook', methods=['POST'])\ndef incoming():\n    handle(request.get_json())\n", "@router.get('/api/webhooks')\ndef list_webhooks(user=Depends(current_user)):\n    return user.webhooks\n"),
 ("error-details-exposed", "app/a.py", "import traceback\n@app.route('/x')\ndef x():\n    try:\n        return run()\n    except Exception:\n        return {'error': traceback.format_exc()}, 500\n", "import traceback\n@app.route('/x')\ndef x():\n    try:\n        return run()\n    except Exception:\n        log.error(traceback.format_exc())\n        return {'error': 'internal error'}, 500\n"),
 ("error-details-exposed", "src/a.js", "app.use((err, req, res, next) => { res.status(500).json({ error: err.stack }); });\n", "app.use((err, req, res, next) => { log(err.stack); res.status(500).json({ error: 'internal' }); });\n"),
 ("materialize-all", "jobs/a.py", "from pyspark.sql import SparkSession\ndef export(df):\n    return df.toPandas()\n", "import polars as pl\ndef export(lf):\n    return lf.collect()\n"),
 ("assert-validation", "app/a.py", "def delete(user, doc):\n    assert user.is_admin\n    doc.delete()\n", "def delete(user, doc):\n    if not user.is_admin:\n        raise PermissionDenied()\n    doc.delete()\n"),
 ("ssrf", "app/a.py", "import requests\n@app.route('/preview')\ndef preview():\n    url = request.args.get('url')\n    return requests.get(url, timeout=5).text\n", "import requests\n@app.route('/preview')\ndef preview():\n    page = request.args.get('page')\n    return requests.get(BASE, params={'page': page}, timeout=5).text\n"),
 # review: a Redis client in a module with no HTTP library
 ("ssrf", "app/a.py", "import httpx\n@app.route('/preview')\ndef preview():\n    url = request.args.get('url')\n    return client.get(url).text\n", "import redis\n@app.route('/value')\ndef value():\n    key = request.args.get('key')\n    return client.get(key)\n"),
 # review2: a session held on self
 ("ssrf", "app/a.py", "import requests\nclass Api:\n    @app.route('/fetch')\n    def fetch(self):\n        url = request.args.get('url')\n        return self.session.get(url).text\n", "import requests\nclass Api:\n    @app.route('/fetch')\n    def fetch(self):\n        name = request.args.get('name')\n        return self.session.get(BASE, params={'q': name}).text\n"),
 ("permissive-cors", "src/a.js", "app.use(cors({ origin: true, credentials: true }));\n", "app.use(cors({ origin: ['https://app.example.com'], credentials: true }));\n"),
 ("permissive-cors", "app/a.py", "CORS(app, supports_credentials=True)\n", "CORS(app, supports_credentials=True, origins=['https://app.example.com'])\n"),
 # review: origins named before the flag, or through resources=
 ("permissive-cors", "app/b.py", "CORS(app, supports_credentials=True, allow_headers=['X-Token'])\n", "CORS(app, origins=['https://app.example.com'], supports_credentials=True)\n"),
 ("permissive-cors", "app/c.py", "CORS(api, supports_credentials=True)\n", "CORS(app, resources={r'/api/*': {'origins': ['https://app.example.com']}}, supports_credentials=True)\n"),
 # review2: origins set through flask-cors's config key
 ("permissive-cors", "app/d.py", "app = Flask(__name__)\nCORS(app, supports_credentials=True)\n", "app = Flask(__name__)\napp.config['CORS_ORIGINS'] = ['https://app.example.com']\nCORS(app, supports_credentials=True)\n"),
 # Blocking in gate by the owner's decision. review and review2: the safe forms stay quiet, a multi-line allowed_classes and
 # a class's own unserialize included.
 ("unsafe-deserialize", "src/Load.java", "Object o = new ObjectInputStream(in).readObject();\n", "ObjectInputStream s = new ObjectInputStream(in);\ns.setObjectInputFilter(ObjectInputFilter.Config.createFilter(\"app.*;!*\"));\nObject o = s.readObject();\n"),
 ("unsafe-deserialize", "app/a.rb", "obj = Marshal.load(params[:blob])\n", "obj = YAML.load(File.read(path))\n"),
 ("unsafe-deserialize", "app/a.php", "$o = unserialize($_POST['data']);\n", "$o = unserialize(\n    $data,\n    ['allowed_classes' => false]\n);\n$p = Serializer::unserialize($data);\n"),
 ("async-predicate", "src/a.ts", "const live = users.filter(async (u) => await isActive(u));\n", "const flags = await Promise.all(users.map((u) => isActive(u)));\nconst live = users.filter((u, i) => flags[i]);\n"),
 ("async-predicate", "src/a.js", "const hit = items.find(async x => check(x));\n", "const hit = items.find(x => check(x));\n"),
 ("unsafe-undocumented", "src/lib.rs", "pub fn read(p: *const u8) -> u8 {\n    unsafe { *p }\n}\n", "pub fn read(p: *const u8) -> u8 {\n    // SAFETY: callers pass a pointer from a live slice, checked non-null above.\n    unsafe { *p }\n}\n"),
 ("unsafe-undocumented", "src/lib.rs", "fn f(v: &[u8]) -> u8 {\n    let x = 1;\n    unsafe {\n        *v.get_unchecked(0)\n    }\n}\n", "fn f(v: &[u8]) -> u8 {\n    unsafe { // Safety: v is never empty, see new().\n        *v.get_unchecked(0)\n    }\n}\n"),
 # review2: a longer SAFETY comment, and a test module
 # review3: `mod tests;` names another file, and a SAFETY block comment or an attribute between still counts
 ("unsafe-undocumented", "src/lib.rs", "#[cfg(test)]\nmod tests;\n\nfn h(p: *const u8) -> u8 {\n    unsafe { *p }\n}\n", "fn h(p: *const u8) -> u8 {\n    /* SAFETY: p points into a live buffer\n       that this module owns. */\n    #[allow(clippy::needless_return)]\n    unsafe { *p }\n}\n"),
 ("unsafe-undocumented", "src/lib.rs", "fn g(p: *const u8) -> u8 {\n    // Reads the first byte.\n    unsafe { *p }\n}\n", "fn g(p: *const u8) -> u8 {\n    // SAFETY: p comes from Vec::as_ptr on a vector\n    // that outlives this call, is never empty,\n    // and nothing writes to it while we read,\n    // as new() documents.\n    unsafe { *p }\n}\n#[cfg(test)]\nmod tests {\n    fn t() { unsafe { std::ptr::null::<u8>().is_null(); } }\n}\n"),
 ("equals-without-hashcode", "src/Money.java", "class Money {\n  @Override\n  public boolean equals(Object o) { return o instanceof Money; }\n}\n", "class Money {\n  @Override\n  public boolean equals(Object o) { return o instanceof Money; }\n  @Override\n  public int hashCode() { return 1; }\n}\n"),
 ("equals-without-hashcode", "src/Money.kt", "class Money(val c: Long) {\n    override fun equals(other: Any?) = other is Money && other.c == c\n}\n", "data class Money(val c: Long)\n"),
 # review: an annotated parameter, or java.lang.Object, still overrides equals
 ("equals-without-hashcode", "src/Id.java", "class Id {\n  public int hashCode() { return 1; }\n}\n", "class Id {\n  public boolean equals(@Nullable java.lang.Object o) { return o == this; }\n  public int hashCode() { return 1; }\n}\n"),
 ("shell-no-strict", "deploy.sh", "#!/bin/bash\nset -e\nbuild | tee build.log\n", "#!/bin/bash\nset -eo pipefail\nbuild | tee build.log\n"),
 # review: a case arm separates patterns with |
 # review2: sh can't take pipefail, and | in a [[ =~ ]] regex or a quoted case arm isn't a pipe
 # review3: a [[ ]] test on a line doesn't hide a real pipe beside it
 ("shell-no-strict", "z.sh", "#!/bin/bash\nset -e\n[[ -f x ]] && cat x | grep y\n", "#!/bin/bash\nset -e\n[[ -f x ]] && grep y x\n"),
 ("shell-no-strict", "x.sh", "#!/usr/bin/env bash\nset -e\nmake | tee log\n", "#!/bin/sh\nset -e\nmake | tee log\n"),
 ("shell-no-strict", "y.sh", "#!/bin/bash\nset -e\n[[ $x =~ ^(a|b)$ ]] && go\nlogs | grep x\n", "#!/bin/bash\nset -e\n[[ $x =~ ^(a|b)$ ]] && go\ncase \"$1\" in\n  'a b'|c) run ;;\nesac\n"),
 ("shell-no-strict", "run.sh", "#!/bin/bash\nset -e\ncase \"$1\" in\n  start|run) go ;;\nesac\nlogs | grep error\n", "#!/bin/bash\nset -e\ncase \"$1\" in\n  start|run) go ;;\nesac\n"),
 ("ignored-error", "app/deploy.py", "import subprocess\ndef deploy():\n    subprocess.run(['make', 'deploy'])\n", "import subprocess\ndef deploy():\n    subprocess.run(['make', 'deploy'], check=True)\n"),
]

# The path decides stdlib-shadowed, so its near misses are other paths with the same text. time.py and os.py are already
# loaded or built in before a script runs, so they can't shadow (review).
STDLIB_NEAR_MISSES = ["app/random.py", "pkg/sub/json.py", "tools/helpers.py", "randomize.py", "test.py", "time.py", "os.py", "_random.py"]

# Severity a case's finding must have, where a rule reports one shape higher than the rest.
SEVERITY = [
    ("assert-validation", "app/a.py", "def delete(user, doc):\n    assert user.is_admin\n    doc.delete()\n", "high"),
    ("assert-validation", "app/a.py", "def delete(user, doc):\n    assert doc.owner_id == user.id\n    doc.delete()\n", "high"),
    # review: a lock's owner and a Raft node's role aren't access checks
    ("assert-validation", "app/a.py", "def release(self, token):\n    assert self._owner == threading.get_ident() and token\n", "low"),
    ("assert-validation", "app/a.py", "def step(self, term):\n    assert self.role == Role.LEADER and term\n", "low"),
    # review2: can_* and a user's groups are too general to call an access check
    ("assert-validation", "app/a.py", "def retry(self, n):\n    assert self.can_retry() and n\n", "low"),
    ("assert-validation", "app/a.py", "def show(user, doc):\n    assert user.groups is not None and doc\n", "low"),
]
