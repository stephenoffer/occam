"""team py: Python rules added or widened for blind P0 cases occam stayed quiet on, each as (rule, path, what should fire, its near miss).

test_scanner_rules.py runs them with the rest. PY_LEADS are the ones test_quality_catalog.py also holds to no-new-send-backs. PY_STOPS are
existing rules that already sent agents back, narrowed here so their near misses stay quiet.
"""

_ROUTES = "from flask import Blueprint\nfrom flask_login import current_user, login_required\nbp = Blueprint('n', __name__)\n"

PY_LEADS = [
    # A fast digest of a password, salted or not. A fast digest of a random key is right, and so is pre-hashing for bcrypt.
    ("weak-password-hash", "app/accounts.py", "import hashlib\ndef store_login(user, passphrase):\n    user.secret_hash = hashlib.sha512(passphrase.encode()).hexdigest()\n",
     "import hashlib\ndef fingerprint(api_key):\n    return hashlib.sha512(api_key.encode()).hexdigest()\n"),
    ("weak-password-hash", "app/accounts.py", "import hashlib\ndef hash_password(pw):\n    return hashlib.sha256(pw.encode()).hexdigest()\n",
     "import base64, bcrypt, hashlib\ndef hash_password(pw):\n    digest = base64.b64encode(hashlib.sha256(pw.encode()).digest())\n    return bcrypt.hashpw(digest, bcrypt.gensalt())\n"),
    # Tokens nobody can guess: not uuid1, and not a hash of an id, an email and the clock.
    ("insecure-random", "app/sharing.py", "import uuid\ndef make_share_token():\n    return uuid.uuid1().hex\n",
     "import uuid\ndef make_trace_id():\n    return uuid.uuid1().hex\n"),
    ("insecure-random", "app/mailing.py",
     "import hashlib, time\ndef new_unsubscribe_token(account):\n    seed = f'{account.id}-{account.email}-{time.time()}'\n    return hashlib.sha1(seed.encode()).hexdigest()\n",
     "import hashlib, secrets\ndef new_unsubscribe_token(account):\n    seed = f'{account.id}-{secrets.token_hex(16)}'\n    return hashlib.sha1(seed.encode()).hexdigest()\n"),
    # An assert about a request goes away under -O. One that only narrows a type checks nothing.
    ("assert-validation", "app/transfers.py",
     "from flask import request\n@app.post('/transfer')\ndef transfer():\n    body = request.get_json()\n    assert body['amount'] > 0, 'amount must be positive'\n    return move(body)\n",
     "@app.get('/me')\n@login_required\ndef me():\n    profile = load_profile()\n    assert profile is not None\n    return profile.as_dict()\n"),
    ("assert-validation", "app/deps.py",
     "from fastapi import Depends\ndef require_admin(claims=Depends(read_claims)):\n    assert 'admin' in claims.roles\n    return claims\n",
     "from fastapi import Depends, HTTPException\ndef require_admin(claims=Depends(read_claims)):\n    if 'admin' not in claims.roles:\n        raise HTTPException(403)\n    return claims\n"),
    # Read, change in Python, commit: by `x.n = x.n + d` as much as `x.n += d`, and through a session held on self.
    ("lost-update", "app/stock.py",
     "def reserve(session, sku, n):\n    row = session.query(Stock).filter_by(sku=sku).one()\n    row.held = row.held + n\n    session.commit()\n",
     "def reserve(session, sku, n):\n    session.query(Stock).filter_by(sku=sku).update({Stock.held: Stock.held + n})\n    session.commit()\n"),
    ("lost-update", "app/points.py",
     "class Points:\n    def spend(self, account, n):\n        account.points -= n\n        self.session.commit()\n",
     "class Points:\n    def spend(self, account_id, n):\n        account = self.session.query(Account).with_for_update().get(account_id)\n        account.points -= n\n        self.session.commit()\n"),
    ("lost-update", "app/quota.py",
     "import threading\nclass Quota:\n    def __init__(self, n):\n        self.left = n\n    def take(self):\n        if self.left > 0:\n            self.left -= 1\n            return True\n        return False\n",
     "import threading\nclass Quota:\n    def __init__(self, n):\n        self.left = n\n        self._lock = threading.Lock()\n    def take(self):\n        with self._lock:\n"
     "            if self.left > 0:\n                self.left -= 1\n                return True\n        return False\n"),
    # Two commits, the second saving a different object: half an operation can be kept. Saving a row and then marking it sent is one record.
    ("multi-write-no-transaction", "app/ledger.py",
     "def move(db, src, dst, amount):\n    src.balance -= amount\n    db.commit()\n    dst.balance += amount\n    db.commit()\n",
     "def signup(db, user):\n    db.add(user)\n    db.commit()\n    user.welcome_sent = True\n    db.commit()\n"),
    ("multi-write-no-transaction", "app/views.py", "def make(order, item):\n    order.save()\n    item.save()\n",
     "def make(request):\n    post = PostForm(request.POST).save(commit=False)\n    post.author = request.user\n    post.save()\n"),
    # Refusing when a row exists, then inserting, races the same way. Catching the unique violation settles it.
    ("check-then-insert", "app/signup.py",
     "def register(db, email):\n    if db.scalar(select(User.id).where(User.email == email)):\n        raise Conflict(email)\n    db.add(User(email=email))\n    db.commit()\n",
     "def register(db, email):\n    if db.scalar(select(User.id).where(User.email == email)):\n        raise Conflict(email)\n    db.add(User(email=email))\n    try:\n"
     "        db.commit()\n    except IntegrityError:\n        db.rollback()\n        raise Conflict(email)\n"),
    # A Celery task that retries itself repeats the charge before the failure.
    ("retry-not-idempotent", "app/tasks.py",
     "@shared_task(autoretry_for=(Exception,), max_retries=5)\ndef settle(order_id):\n    gateway.charge(order_id)\n    mark_paid(order_id)\n",
     "@shared_task(autoretry_for=(Exception,), max_retries=5)\ndef settle(order_id):\n    gateway.charge(order_id, idempotency_key=f'settle-{order_id}')\n    mark_paid(order_id)\n"),
    # argtypes with no restype: a handle comes back as a C int.
    ("ctypes-untyped", "app/queue.py",
     "import ctypes\nlib = ctypes.CDLL('libq.so')\nlib.q_open.argtypes = [ctypes.c_char_p]\nlib.q_read.argtypes = [ctypes.c_void_p]\nlib.q_read.restype = ctypes.c_int\n"
     "h = lib.q_open(b'x')\nlib.q_read(h)\n",
     "import ctypes\nlib = ctypes.CDLL('libq.so')\nlib.q_open.argtypes = [ctypes.c_char_p]\nlib.q_open.restype = ctypes.c_void_p\nlib.q_read.argtypes = [ctypes.c_void_p]\n"
     "lib.q_read.restype = ctypes.c_int\nh = lib.q_open(b'x')\nlib.q_read(h)\n"),
    # pathlib's open("w"), with one file named through a parameter's default.
    ("nonatomic-state-write", "app/state.py",
     "import json\nfrom pathlib import Path\nSTATE = Path('state.json')\ndef load(path=STATE):\n    with path.open() as fh:\n        return json.load(fh)\n"
     "def save(data, path=STATE):\n    with path.open('w') as fh:\n        json.dump(data, fh)\n",
     "import json, os\nfrom pathlib import Path\nSTATE = Path('state.json')\ndef load(path=STATE):\n    with path.open() as fh:\n        return json.load(fh)\n"
     "def save(data, path=STATE):\n    tmp = path.with_suffix('.tmp')\n    with tmp.open('w') as fh:\n        json.dump(data, fh)\n    os.replace(tmp, path)\n"),
    # What an agent started from code may do, and which credentials it gets.
    ("agent-permission-widened", "scripts/triage.py", "options = AgentOptions(permission_mode='bypassPermissions', allowed_tools=['Read'])\n",
     "options = AgentOptions(permission_mode='acceptEdits', allowed_tools=['Read'])\n"),
    ("agent-permission-widened", "scripts/triage.py", "import os\nopts = ClaudeAgentOptions(env=dict(os.environ))\n",
     "import os\nopts = ClaudeAgentOptions(env={'GH_TOKEN': os.environ['GH_TOKEN']})\n"),
    ("agent-permission-widened", "scripts/triage.py", "import subprocess\nsubprocess.run(['claude', '-p', task, '--dangerously-skip-permissions'])\n",
     "import subprocess\nsubprocess.run(['claude', '-p', task, '--permission-mode', 'plan'])\n"),
    # A request's headers carry its credential, in a log line or in an error sent back.
    ("sensitive-log", "app/client.py",
     "import logging\nlog = logging.getLogger(__name__)\ndef trace(response):\n    sent = response.request\n    log.info('sent %s', dict(sent.headers))\n",
     "import logging\nlog = logging.getLogger(__name__)\ndef trace(response):\n    sent = response.request\n    log.info('sent %s', scrub(sent.headers))\n"),
    ("error-details-exposed", "app/client.py",
     "from fastapi import HTTPException\ndef fail(resp):\n    raise HTTPException(502, detail={'upstream': resp.status_code, 'headers': dict(resp.request.headers)})\n",
     "from fastapi import HTTPException\ndef fail(resp):\n    raise HTTPException(502, detail={'upstream': resp.status_code})\n"),
    ("mass-assignment", "app/items.py",
     "from flask import request\ndef edit(item):\n    payload = request.get_json()\n    for field, value in payload.items():\n        setattr(item, field, value)\n",
     "from flask import request\nEDITABLE = {'title', 'notes'}\ndef edit(item):\n    payload = request.get_json()\n    for field, value in payload.items():\n"
     "        if field in EDITABLE:\n            setattr(item, field, value)\n"),
    ("weak-path-check", "app/files.py",
     "import os\ndef inside(root, name):\n    full = os.path.realpath(os.path.join(root, name))\n    if not full.startswith(root):\n        raise ValueError(name)\n    return full\n",
     "import os\ndef inside(root, name):\n    full = os.path.realpath(os.path.join(root, name))\n    if not full.startswith(root + os.sep):\n        raise ValueError(name)\n    return full\n"),
    ("ssrf", "app/fetch.py",
     "import requests\nDENY = ('localhost', '127.0.0.1')\ndef fetch(url):\n    host = urlparse(url).hostname\n    if host in DENY:\n        raise ValueError(url)\n    return requests.get(url, timeout=5)\n",
     "import requests\nALLOW = {'api.partner.example'}\ndef fetch(url):\n    host = urlparse(url).hostname\n    if host not in ALLOW:\n        raise ValueError(url)\n    return requests.get(url, timeout=5)\n"),
    ("ssrf", "app/proxy.py",
     "import requests\nfrom flask import request\n@app.get('/proxy')\ndef proxy():\n    target = request.args.get('u')\n    return requests.get(target, timeout=3).text\n",
     "import requests\nfrom flask import request\n@app.get('/proxy')\ndef proxy():\n    target = request.args.get('u')\n    if urlparse(target).hostname not in PARTNERS:\n"
     "        return 'not allowed', 400\n    return requests.get(target, timeout=3).text\n"),
    # Cookie-authenticated GETs that change data, in Flask and in Django.
    ("state-change-on-get", "app/items.py",
     _ROUTES + "@bp.get('/items/<int:i>/archive')\n@login_required\ndef archive(i):\n    item = Item.query.get(i)\n    item.archived = True\n    db.session.commit()\n    return 'ok'\n",
     _ROUTES + "@bp.post('/items/<int:i>/archive')\n@login_required\ndef archive(i):\n    item = Item.query.get(i)\n    item.archived = True\n    db.session.commit()\n    return 'ok'\n"),
    ("state-change-on-get", "cards/views.py",
     "@login_required\ndef remove_card(request, pk):\n    Card.objects.filter(pk=pk, owner=request.user).delete()\n    return redirect('cards')\n",
     "@login_required\n@require_POST\ndef remove_card(request, pk):\n    Card.objects.filter(pk=pk, owner=request.user).delete()\n    return redirect('cards')\n"),
    ("unscoped-lookup", "app/notes.py",
     _ROUTES + "@bp.get('/notes')\n@login_required\ndef notes():\n    return Note.query.filter_by(author_id=current_user.id).all()\n"
     "@bp.get('/notes/<int:n>')\n@login_required\ndef note(n):\n    return Note.query.get_or_404(n).text\n",
     _ROUTES + "@bp.get('/notes')\n@login_required\ndef notes():\n    return Note.query.filter_by(author_id=current_user.id).all()\n"
     "@bp.get('/notes/<int:n>')\n@login_required\ndef note(n):\n    return Note.query.filter_by(id=n, author_id=current_user.id).first_or_404().text\n"),
    ("missing-auth", "audit/views.py",
     "class LogList(PermissionRequiredMixin, ListView):\n    permission_required = 'audit.view'\n    model = Entry\n"
     "class LogPurge(LoginRequiredMixin, FormView):\n    def form_valid(self, form):\n        Entry.objects.filter(day__lt=form.cleaned_data['day']).delete()\n        return super().form_valid(form)\n",
     "class LogList(PermissionRequiredMixin, ListView):\n    permission_required = 'audit.view'\n    model = Entry\n"
     "class LogPurge(PermissionRequiredMixin, FormView):\n    permission_required = 'audit.purge'\n    def form_valid(self, form):\n"
     "        Entry.objects.filter(day__lt=form.cleaned_data['day']).delete()\n        return super().form_valid(form)\n"),
    ("tool-call-unchecked", "agent/run.py",
     "import json\ndef run(tools, call):\n    return getattr(tools, call.function.name)(**json.loads(call.function.arguments))\n",
     "import json\ndef run(tools, call):\n    if call.function.name not in REGISTRY:\n        return 'unknown tool'\n    return getattr(tools, call.function.name)(**json.loads(call.function.arguments))\n"),
    ("tool-call-unchecked", "agent/cleanup.py",
     "import os\ndef apply(resp):\n    for block in resp.content:\n        for path in block.input['paths']:\n            os.remove(path)\n",
     "import os\ndef apply(resp, offered):\n    for block in resp.content:\n        for path in block.input['paths']:\n            if isinstance(path, str) and path in offered:\n                os.remove(path)\n"),
    # Stores told not to make writes durable, and offsets committed ahead of the writes they count.
    ("durability-disabled", "app/events.py", "producer = KafkaProducer(bootstrap_servers=BROKERS, acks=0)\n",
     "producer = KafkaProducer(bootstrap_servers=BROKERS, acks='all')\n"),
    ("durability-disabled", "app/queue.py", "def open_store(conn):\n    conn.execute('PRAGMA synchronous=OFF')\n",
     "def open_store(conn):\n    conn.execute('PRAGMA journal_mode=WAL')\n    conn.execute('PRAGMA synchronous=NORMAL')\n"),
    ("auto-commit-before-write", "app/loader.py",
     "def load():\n    consumer = KafkaConsumer('t', enable_auto_commit=True)\n    batch = []\n    for msg in consumer:\n        batch.append(msg.value)\n"
     "        if len(batch) >= 100:\n            write(batch)\n            batch.clear()\n",
     "def load():\n    consumer = KafkaConsumer('t', enable_auto_commit=False)\n    batch = []\n    for msg in consumer:\n        batch.append(msg.value)\n"
     "        if len(batch) >= 100:\n            write(batch)\n            consumer.commit()\n            batch.clear()\n"),
    # Memory handed to C: an array of whatever dtype, and a callback nothing keeps.
    ("ctypes-buffer-unchecked", "app/native.py",
     "import ctypes\nimport numpy as np\ndef total(lib, xs):\n    a = np.asarray(xs)\n    return lib.sum_f(a.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), a.size)\n",
     "import ctypes\nimport numpy as np\ndef total(lib, xs):\n    a = np.ascontiguousarray(xs, dtype=np.float32)\n    return lib.sum_f(a.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), a.size)\n"),
    ("ctypes-callback-collected", "app/native.py",
     "import ctypes\nON_EVENT = ctypes.CFUNCTYPE(None, ctypes.c_int)\ndef watch(lib, handler):\n    lib.register_listener(ON_EVENT(handler))\n",
     "import ctypes\nON_EVENT = ctypes.CFUNCTYPE(None, ctypes.c_int)\nCMP = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)\n"
     "def watch(lib, handler):\n    keep = ON_EVENT(handler)\n    lib.register_listener(keep)\n    return keep\ndef order(lib, buf, n):\n    lib.qsort(buf, n, 8, CMP(compare))\n"),
    ("rebuilt-while-shared", "app/peers.py",
     "import threading\nclass Peers:\n    def __init__(self):\n        self.hosts = []\n        threading.Thread(target=self.poll, daemon=True).start()\n"
     "    def poll(self):\n        self.hosts.clear()\n        for h in discover():\n            self.hosts.append(h)\n",
     "import threading\nclass Peers:\n    def __init__(self):\n        self.hosts = []\n        threading.Thread(target=self.poll, daemon=True).start()\n"
     "    def poll(self):\n        fresh = [h for h in discover()]\n        self.hosts = fresh\n"),
    # A script fetched and made executable runs whatever the server sends next. Checking a recorded hash first doesn't.
    ("unverified-download-exec", "scripts/install_tools.py",
     "import os, urllib.request\ndef install(url, dest):\n    with urllib.request.urlopen(url, timeout=10) as r:\n        data = r.read()\n"
     "    with open(dest, 'wb') as fh:\n        fh.write(data)\n    os.chmod(dest, 0o755)\n",
     "import hashlib, os, urllib.request\nEXPECTED = 'ab12'\ndef install(url, dest):\n    with urllib.request.urlopen(url, timeout=10) as r:\n        data = r.read()\n"
     "    if hashlib.sha256(data).hexdigest() != EXPECTED:\n        raise ValueError(url)\n    with open(dest, 'wb') as fh:\n        fh.write(data)\n    os.chmod(dest, 0o755)\n"),
    # An upload let through on its name alone. A size cap or a look at the bytes is more than the name.
    ("upload-extension-only", "app/uploads.py",
     "import os\nfrom flask import request\nOK = {'pdf'}\ndef upload():\n    f = request.files['doc']\n    if f.filename.rsplit('.', 1)[-1].lower() not in OK:\n"
     "        return 'bad', 400\n    f.save(os.path.join('/srv/static', f.filename))\n    return 'ok'\n",
     "import os\nfrom flask import request\nOK = {'pdf'}\ndef upload():\n    f = request.files['doc']\n    if f.filename.rsplit('.', 1)[-1].lower() not in OK:\n"
     "        return 'bad', 400\n    if f.content_length > 5_000_000 or f.stream.read(5) != b'%PDF-':\n        return 'bad', 400\n"
     "    f.save(os.path.join('/srv/uploads', f.filename))\n    return 'ok'\n"),
    ("upload-extension-only", "imports/forms.py",
     "from django import forms\nfrom django.core.validators import FileExtensionValidator\nclass Upload(forms.Form):\n"
     "    sheet = forms.FileField(validators=[FileExtensionValidator(['csv'])])\n",
     "from django import forms\nfrom django.core.validators import FileExtensionValidator\nclass Upload(forms.Form):\n"
     "    sheet = forms.FileField(validators=[FileExtensionValidator(['csv'])])\n    def clean_sheet(self):\n        f = self.cleaned_data['sheet']\n"
     "        if f.size > 2_000_000:\n            raise forms.ValidationError('too large')\n        return f\n"),
    # An error path that decodes the token unverified and carries on lets a forged token in. Reading the claims to log them and then denying
    # doesn't, and neither does python-jose's get_unverified_claims there (review).
    ("fail-open", "app/auth.py",
     "import jwt\ndef claims_for(token, keys):\n    try:\n        return jwt.decode(token, keys.current(), algorithms=['RS256'])\n    except KeyError:\n"
     "        claims = jwt.decode(token, options={'verify_signature': False})\n    return claims\n",
     "import jwt\nfrom flask import abort\ndef claims_for(token, keys):\n    try:\n        return jwt.decode(token, keys.current(), algorithms=['HS256'])\n"
     "    except jwt.ExpiredSignatureError:\n        claims = jwt.decode(token, options={'verify_signature': False})\n        log.info('expired for %s', claims.get('sub'))\n"
     "        abort(401)\n"),
    ("fail-open", "app/auth.py",
     "import jwt\ndef claims_for(token, keys):\n    try:\n        return jwt.decode(token, keys.current(), algorithms=['RS256'])\n    except KeyError:\n"
     "        return jwt.decode(token, options={'verify_signature': False})\n",
     "from jose import ExpiredSignatureError, jwt\nfrom fastapi import HTTPException\ndef decode_or_401(token):\n    try:\n        return jwt.decode(token, KEY, algorithms=['RS256'])\n"
     "    except ExpiredSignatureError:\n        claims = jwt.get_unverified_claims(token)\n        log.info('expired for %s', claims.get('sub'))\n"
     "        raise HTTPException(status_code=401)\n"),
    # review: a GET of a form bound to request.POST is never valid, and an early return for anything but POST guards what follows.
    ("state-change-on-get", "app/views.py",
     "@login_required\ndef edit_profile(request):\n    form = ProfileForm(request.GET, instance=request.user.profile)\n    if form.is_valid():\n        form.save()\n"
     "    return render(request, 'edit.html', {'form': form})\n",
     "@login_required\ndef edit_profile(request):\n    form = ProfileForm(request.POST or None, instance=request.user.profile)\n    if form.is_valid():\n        form.save()\n"
     "        return redirect('profile')\n    return render(request, 'edit.html', {'form': form})\n"),
    ("state-change-on-get", "app/views.py",
     "@login_required\ndef delete_item(request, pk):\n    Item.objects.filter(pk=pk, owner=request.user).delete()\n    return redirect('items')\n",
     "@login_required\ndef delete_item(request, pk):\n    if request.method != 'POST':\n        return HttpResponseNotAllowed(['POST'])\n"
     "    Item.objects.filter(pk=pk, owner=request.user).delete()\n    return redirect('items')\n"),
    # review: a check on one table before writing another isn't check-then-insert.
    ("check-then-insert", "app/views.py",
     "def add_tag(request, name):\n    if Tag.objects.filter(name=name).exists():\n        return HttpResponseBadRequest('taken')\n    Tag.objects.create(name=name)\n",
     "def add_comment(request, pk):\n    if Ban.objects.filter(user_id=request.user.id).exists():\n        return HttpResponseForbidden()\n"
     "    Comment.objects.create(post_id=pk, text=request.POST['text'])\n"),
    # review: returning a different URL for localhost isn't refusing it.
    ("ssrf", "app/fetch.py",
     "import requests\ndef fetch(url, host):\n    if host == 'localhost':\n        return None\n    return requests.get(url, timeout=5)\n",
     "import requests\nclass Client:\n    def __init__(self, host):\n        self.host = host\n    def base_url(self):\n        if self.host == 'localhost':\n"
     "            return 'http://localhost:8000'\n        return f'https://{self.host}'\n    def get(self, path):\n        return requests.get(self.base_url() + path, timeout=10).json()\n"),
    # review: np.zeros with no dtype is float64 and contiguous, which matches c_double. Passed as c_float, it's the wrong width.
    ("ctypes-buffer-unchecked", "app/ffi.py",
     "import ctypes\nfrom ctypes import POINTER, c_float\nimport numpy as np\ndef smooth(lib, n):\n    out = np.zeros(n)\n    lib.smooth(out.ctypes.data_as(POINTER(c_float)), n)\n    return out\n",
     "import ctypes\nfrom ctypes import POINTER, c_double\nimport numpy as np\ndef smooth(lib, n):\n    out = np.zeros(n)\n    lib.smooth(out.ctypes.data_as(POINTER(c_double)), n)\n    return out\n"),
    # review: importing flask isn't evidence of threads; a module-level instance shared by request handlers is.
    ("lost-update", "app/web.py",
     "from flask import Flask\napp = Flask(__name__)\nclass Limiter:\n    def __init__(self, limit):\n        self.left = limit\n    def take(self):\n"
     "        if self.left > 0:\n            self.left -= 1\n            return True\n        return False\nLIMITER = Limiter(100)\n",
     "from flask import Flask\napp = Flask(__name__)\nclass Backoff:\n    def __init__(self, limit):\n        self.attempt = 0\n        self.limit = limit\n"
     "    def next_delay(self):\n        if self.attempt < self.limit:\n            self.attempt += 1\n            return 2 ** self.attempt\n        return None\n"),
    # review: a read-only SELECT through execute isn't destructive, and neither is dict.update.
    ("tool-call-unchecked", "app/agent.py",
     "import json\ndef run_tools(conn, message):\n    for call in message.tool_calls:\n        args = json.loads(call.function.arguments)\n"
     "        conn.execute('DELETE FROM orders WHERE customer = ?', (args['customer'],))\n",
     "import json\ndef run_tools(conn, message, seen):\n    results = []\n    for call in message.tool_calls:\n        args = json.loads(call.function.arguments)\n"
     "        seen.update(args)\n        cur = conn.execute('SELECT id, total FROM orders WHERE customer = ?', (args['customer'],))\n        results.append(cur.fetchall())\n    return results\n"),
    # review: a module constant ending in a separator is a safe root.
    ("weak-path-check", "app/paths.py",
     "import os\nUPLOAD_ROOT = '/srv/uploads'\ndef open_upload(name):\n    real = os.path.realpath(os.path.join(UPLOAD_ROOT, name))\n    if not real.startswith(UPLOAD_ROOT):\n"
     "        raise PermissionError(name)\n    return open(real, 'rb')\n",
     "import os\nUPLOAD_ROOT = '/srv/uploads/'\ndef open_upload(name):\n    real = os.path.realpath(os.path.join(UPLOAD_ROOT, name))\n    if not real.startswith(UPLOAD_ROOT):\n"
     "        raise PermissionError(name)\n    return open(real, 'rb')\n"),
    # review: Flask's documented upload pattern, saved privately, may have its size capped in configuration elsewhere.
    ("upload-extension-only", "app/upload.py",
     "import os, subprocess\nfrom flask import request\nOK = {'png', 'jpg'}\ndef upload():\n    f = request.files['file']\n    if f.filename.rsplit('.', 1)[1].lower() in OK:\n"
     "        path = os.path.join('/srv/uploads', f.filename)\n        f.save(path)\n        subprocess.run(['convert', path, '-thumbnail', '64x64', path + '.jpg'])\n",
     "import os\nfrom flask import Flask, request\nfrom werkzeug.utils import secure_filename\napp = Flask(__name__)\napp.config.from_object('config')\n"
     "ALLOWED_EXTENSIONS = {'png', 'jpg'}\ndef allowed_file(filename):\n    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS\n"
     "@app.route('/upload', methods=['POST'])\ndef upload():\n    file = request.files['file']\n    if file and allowed_file(file.filename):\n"
     "        file.save(os.path.join('/srv/uploads', secure_filename(file.filename)))\n        return 'ok'\n    return 'bad', 400\n"),
    # review: a cache key isn't a secret, and a random reset token hashed for storage isn't a password.
    ("insecure-random", "app/tasks.py",
     "import hashlib\ndef make_reset_token(user):\n    return hashlib.md5(f'{user.pk}'.encode()).hexdigest()\n",
     "import hashlib\ndef make_reset_cache_key(user):\n    return hashlib.md5(f'{user.pk}'.encode()).hexdigest()\n"),
    ("weak-password-hash", "app/tasks.py",
     "import hashlib\ndef store_password(user, new_password):\n    user.secret = hashlib.sha256(new_password.encode()).hexdigest()\n",
     "import hashlib\ndef store_reset(user, password_reset_token):\n    user.reset_digest = hashlib.sha256(password_reset_token.encode()).hexdigest()\n    user.save()\n"),
    # Templates turning escaping off. tojson escapes for a script itself.
    ("xss-sink", "app/templates/post.html", "<p>{{ comment.text|safe }}</p>\n", "<script>var cfg = {{ cfg|tojson|safe }};</script>\n"),
]

PY_STOPS = [
    # Existing rules that send the agent back, narrowed so their near misses stay quiet: SQL built only from an allow-list, from literal clauses, or by a helper that does the same isn't injection. Anything else still is.
    ("sql-injection", "app/orders.py", "def page(db, sort):\n    db.execute(f'SELECT * FROM orders ORDER BY {sort}')\n",
     "ORDER = {'new': 'created_at DESC', 'old': 'created_at'}\ndef _order(sort):\n    return f'ORDER BY {ORDER[sort]}'\n"
     "def page(db, sort, shop):\n    clauses = ['shop_id = :shop']\n    clauses.append('deleted_at IS NULL')\n"
     "    db.execute(f\"SELECT * FROM orders WHERE {' AND '.join(clauses)} {_order(sort)}\", {'shop': shop})\n"),
    ("sql-injection", "app/orders.py",
     "def page(db, extra):\n    clauses = ['a = 1']\n    clauses.append(extra)\n    db.execute(f\"SELECT * FROM t WHERE {' AND '.join(clauses)}\")\n",
     "def page(db):\n    clauses = ['a = 1']\n    clauses.append('b = 2')\n    db.execute(f\"SELECT * FROM t WHERE {' AND '.join(clauses)}\")\n"),
    ("sql-injection", "app/orders.py", "def _order(sort):\n    return f'ORDER BY {sort}'\ndef page(db, sort):\n    db.execute(f'SELECT * FROM t {_order(sort)}')\n",
     "COLUMNS = {'a': 'name'}\ndef _order(sort):\n    return f'ORDER BY {COLUMNS.get(sort, \"id\")}'\ndef page(db, sort):\n    db.execute(f'SELECT * FROM t {_order(sort)}')\n"),
    # A shell command whose every runtime piece went through shlex.quote can't be split or extended by the values.
    ("shell-injection", "app/media.py",
     "import shlex, subprocess\ndef thumb(src, title):\n    q = shlex.quote\n    cmd = f'convert {q(src)} -set comment {title} out.png'\n    subprocess.run(cmd, shell=True)\n",
     "import shlex, subprocess\ndef thumb(src, title):\n    q = shlex.quote\n    cmd = f'convert {q(src)} -set comment {q(title)} out.png'\n    subprocess.run(cmd, shell=True)\n"),
]

PY_TEST_FILE_CASES = [
    ("live-credential-in-test", "tests/conftest.py", "DB = 'postgresql://app:s3cr3tpw@billing.prod.internal:5432/app'\n",
     "DB = 'postgresql://app:app@localhost:5432/app_test'\n"),
    ("live-credential-in-test", "tests/conftest.py", "DB = 'mysql+pymysql://svc:Xq81zz@orders.c1abc.us-east-1.rds.amazonaws.com/orders'\n",
     "DB = os.environ.get('TEST_DATABASE_URL', 'mysql+pymysql://svc:svc@127.0.0.1/orders_test')\n"),
]

PY_CASES = [*PY_LEADS, *PY_STOPS, *PY_TEST_FILE_CASES]
