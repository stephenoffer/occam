"""Checks in rules_js.py, each as (rule, path, what should fire, its near miss). test_scanner_rules.py runs them with the rest."""

_ROUTES = ("const router = express.Router();\n"
           "router.get('/orders', requireUser, async (req, res) => res.json(await list(req.user)));\n"
           "router.post('/orders', requireUser, async (req, res) => res.json(await create(req.body)));\n"
           "router.get('/health', (req, res) => res.send('ok'));\n")

JS_CASES = [
 ("missing-auth", "src/routes.js", _ROUTES + "router.delete('/orders/:id', async (req, res) => res.json(await remove(req.params.id)));\n",
  _ROUTES + "router.delete('/orders/:id', requireUser, async (req, res) => res.json(await remove(req.params.id)));\n"),
 ("missing-auth", "src/routes.ts", _ROUTES + "router.put('/orders/:id', async (req: Request, res: Response) => res.json(await save(req.body)));\n",
  "router.use(requireUser);\n" + _ROUTES + "router.put('/orders/:id', async (req: Request, res: Response) => res.json(await save(req.body)));\n"),
 ("fail-open", "src/auth.js", "export function requireUser(req, res, next) {\n  if (!req.headers.authorization) return res.status(401).end();\n  try {\n    req.user = jwt.verify(req.headers.authorization, KEY);\n    next();\n  } catch (err) {\n    next();\n  }\n}\n",
  "export function requireUser(req, res, next) {\n  if (!req.headers.authorization) return res.status(401).end();\n  try {\n    req.user = jwt.verify(req.headers.authorization, KEY);\n    next();\n  } catch (err) {\n    next(err);\n  }\n}\n"),
 # From the review: optional auth attaches a user when it can and never refuses, so going on without one is its job.
 ("fail-open", "src/auth.js", "export function requireUser(req, res, next) {\n  if (!req.headers.authorization) return res.sendStatus(403);\n  try {\n    req.user = jwt.verify(req.headers.authorization, KEY);\n  } catch (err) {\n    return next();\n  }\n  next();\n}\n",
  "function attachUser(req, res, next) {\n  try {\n    req.user = jwt.verify(req.headers.authorization, KEY);\n    next();\n  } catch (err) {\n    req.user = null;\n    next();\n  }\n}\n"),
 ("multi-write-no-transaction", "src/transfer.ts", "export async function transfer(from, to, amount) {\n  await prisma.account.update({ where: { id: from }, data: { balance: { decrement: amount } } });\n  await prisma.account.update({ where: { id: to }, data: { balance: { increment: amount } } });\n}\n",
  "export async function transfer(from, to, amount) {\n  await prisma.$transaction([\n    prisma.account.update({ where: { id: from }, data: { balance: { decrement: amount } } }),\n    prisma.account.update({ where: { id: to }, data: { balance: { increment: amount } } }),\n  ]);\n}\n"),
 ("unpaginated-query", "src/users.ts", "app.get('/users', async (req, res) => res.json(await prisma.user.findMany({ where: { active: true } })));\n",
  "app.get('/users', async (req, res) => res.json(await prisma.user.findMany({ where: { active: true }, take: 50 })));\n"),
 ("client-per-call", "src/db.ts", "export async function handler(event) {\n  const prisma = new PrismaClient();\n  return prisma.user.count();\n}\n",
  "const prisma = new PrismaClient();\nexport async function handler(event) {\n  return prisma.user.count();\n}\n"),
 ("client-per-call", "src/db.js", "app.get('/n', async (req, res) => {\n  const pool = new Pool({ connectionString: URL });\n  res.json(await pool.query('select 1'));\n});\n",
  "const globalForPrisma = globalThis;\nexport const prisma = globalForPrisma.prisma || new PrismaClient();\nexport function createPool(url: string) {\n  return new Pool({ connectionString: url });\n}\nasync function main() {\n  const prisma = new PrismaClient();\n  await seed(prisma);\n}\n"),
 ("mock-of-subject", "src/__tests__/cart.test.ts", "import { total } from '../cart';\njest.mock('../cart');\ntest('total', () => expect(total([1, 2])).toBe(3));\n",
  "import { total } from '../cart';\njest.mock('../prices');\ntest('total', () => expect(total([1, 2])).toBe(3));\n"),
 ("dead-control", "src/Save.tsx", "export const Save = () => <button onClick={() => {}}>Save</button>;\n", "export const Save = ({ save }) => <button onClick={() => save()}>Save</button>;\n"),
 ("dead-control", "src/Nav.jsx", "export const Nav = () => <a href=\"#\">Pricing</a>;\n", "export const Nav = () => <a href=\"#\" onClick={openPricing}>Pricing</a>;\n"),
 ("a11y-missing", "src/Card.tsx", "export const Card = ({ open }) => <div role=\"button\" onClick={open}>Open</div>;\n", "export const Card = ({ open }) => <div role=\"button\" tabIndex={0} onKeyDown={open} onClick={open}>Open</div>;\n"),
 ("a11y-missing", "src/Close.tsx", "export const Close = ({ close }) => <button onClick={close}><XIcon /></button>;\n", "export const Close = ({ close }) => <button aria-label=\"Close\" onClick={close}><XIcon /></button>;\n"),
 ("a11y-missing", "src/Search.tsx", "export const Search = () => <input type=\"search\" placeholder=\"Search\" />;\n", "export const Search = () => <input type=\"search\" aria-label=\"Search\" placeholder=\"Search\" />;\n"),
 # From the review: what each check must leave alone, and forms it missed.
 ("multi-write-no-transaction", "src/transfer.ts", "export class Bank {\n  async transfer(from: string, to: string): Promise<void> {\n    await prisma.account.update({ where: { id: from }, data: {} });\n    await prisma.account.update({ where: { id: to }, data: {} });\n  }\n}\n",
  "export async function rename(id: string, name: string): Promise<void> {\n  await db.user.update({ where: { id }, data: { name } });\n  await cache.delete(`user:${id}`);\n}\n"),
 ("missing-auth", "src/routes.js", _ROUTES + "router.delete('/orders/:id', ctl.remove);\n", _ROUTES + "router.delete('/orders/:id', requireUser, ctl.remove);\n"),
 ("unpaginated-query", "src/users.ts", "app.get('/users', async (req, res) => {\n  res.json(await prisma.user.findMany({ where: { active: true } }));\n});\n",
  "app.get('/orders/:id/items', async (req, res) => res.json(await prisma.orderItem.findMany({ where: { orderId: req.params.id } })));\nexport async function load(ids) {\n  return prisma.user.findMany({ where: { active: true } });\n}\n"),
 ("mock-of-subject", "src/routes/users.test.ts", "jest.mock('./users');\n", "jest.mock('../services/users');\n"),
 ("a11y-missing", "src/Search.tsx", "export const Search = () => <input onChange={(e) => setQ(e.target.value)} />;\n",
  "export const Search = () => <input onChange={(e) => setQ(e.target.value)} aria-label=\"Search\" />;\nexport const Name = () => <label>Name <input name=\"name\" /></label>;\nexport const Close = ({ close }) => <button title=\"Close\" onClick={close}><XIcon /></button>;\nexport const Card = ({ open }) => <div role=\"button\" onClick={() => open()} tabIndex={0}>Open</div>;\n"),
 ("dead-control", "src/Nav.jsx", "export const Nav = () => <a href=\"#\" className=\"nav\">Pricing</a>;\n", "export const Menu = () => <a href=\"#\" className=\"dropdown-toggle\" data-bs-toggle=\"dropdown\">Menu</a>;\n"),
 # From occam-97's review of the committed rules.
 ("fail-open", "src/auth.ts", "export function requireUser(req, res, next) {\n  if (!req.headers.authorization) return res.status(401).end();\n  try {\n    req.user = jwt.verify(req.headers.authorization, KEY);\n    next();\n  } catch (err) {\n    next();\n  }\n}\n",
  "export function requireUser(req, res, next) {\n  if (!req.headers.authorization) return res.status(401).end();\n  try {\n    req.user = jwt.verify(req.headers.authorization, KEY);\n    next();\n  } catch (err) {\n    if (err.name === 'TokenExpiredError') {\n      refresh(req);\n      return next();\n    }\n    return res.status(401).end();\n  }\n}\n"
  "export function attachUser(req: express.Request, res: express.Response, next: express.NextFunction) {\n  try {\n    req.user = jwt.verify(req.headers.authorization, KEY);\n  } catch (err) {\n    req.user = null;\n  }\n  next();\n}\n"),
 ("multi-write-no-transaction", "src/a.ts", "export async function move(a, b) {\n  await prisma.item.update({ where: { id: a } });\n  await prisma.item.update({ where: { id: b } });\n}\n",
  "export async function bill(id) {\n  await stripe.customers.update(id, {});\n  await stripe.subscriptions.update(id, {});\n  await cache.delete(id);\n  await cache.delete(`x${id}`);\n}\n"),
 ("dead-control", "src/Save.tsx", "export const Save = () => <button onClick={() => {}}>Save</button>;\n", "export const Field = ({ v }) => <input value={v} onChange={() => {}} />;\nconst html = `<a href=\"#\">x</a>`;\n"),
 ("mock-of-subject", "src/cart.test.ts", "jest.mock('./cart');\n", "jest.mock('./cart', () => ({ ...jest.requireActual('./cart'), price: jest.fn() }));\n"),
 ("missing-auth", "src/routes.js", _ROUTES + "router.delete('/orders/:id', ctl.remove);\n", "router.get('/a', csrfProtection, async (req, res) => res.send(1));\nrouter.get('/b', csrfProtection, async (req, res) => res.send(2));\nrouter.post('/c', csrfProtection, async (req, res) => res.send(3));\nrouter.get('/d', async (req, res) => res.send(4));\n"),
 # From the third review: a neighbor's requireActual doesn't make this mock partial.
 ("mock-of-subject", "src/cart.test.ts", "jest.mock('./cart');\njest.mock('../lib/http', () => ({ ...jest.requireActual('../lib/http'), get: jest.fn() }));\n",
  "jest.mock('./cart', () => ({ ...jest.requireActual('./cart'), price: jest.fn() }));\n"),
 ("multi-write-no-transaction", "src/users.ts", "export async function retire(id) {\n  await User.update({ active: false }, { where: { id } });\n  await User.destroy({ where: { id } });\n}\n",
  "export async function retire(id) {\n  await sequelize.transaction(async (t) => {\n    await User.update({ active: false }, { where: { id }, transaction: t });\n    await User.destroy({ where: { id }, transaction: t });\n  });\n}\n"),
]

# Team js (recall fixes): request values followed to their sinks, settings that switch a defense off, and state changed or acknowledged unsafely.
# Each is written for this table, not taken from the blind cases.
_EXPRESS = "const express = require('express');\nconst router = express.Router();\n"
_KOA_FETCH = ("router.get('/preview', async (ctx) => {\n  const target = ctx.query.link;\n  const page = await got(target);\n  ctx.body = page.body;\n});\n")
JS_RECALL_CASES = [
 ("ssrf", "src/routes/preview.js", _EXPRESS + "router.get('/preview', async (req, res) => {\n  const { link } = req.query;\n  const page = await axios.get(link);\n  res.send(page.data);\n});\n",
  _EXPRESS + "const BASE = 'https://api.example.com';\nrouter.get('/preview', async (req, res) => {\n  const id = req.query.id;\n  const page = await axios.get(`${BASE}/items/${encodeURIComponent(id)}`);\n  res.send(page.data);\n});\n"),
 ("ssrf", "app/api/thumb/route.ts", "export async function GET(req: Request) {\n  const src = new URL(req.url).searchParams.get('u');\n  const upstream = await fetch(src!);\n  return new Response(upstream.body);\n}\n",
  "const ALLOWED = new Set(['images.example.com']);\nexport async function GET(req: Request) {\n  const src = new URL(req.url).searchParams.get('u')!;\n  if (!ALLOWED.has(new URL(src).hostname)) return new Response(null, { status: 400 });\n  return new Response((await fetch(src)).body);\n}\n"),
 ("ssrf", "src/preview.js", _KOA_FETCH, "router.get('/preview', async (ctx) => {\n  const res = await fetch(SERVICE_URL, { method: 'POST', body: JSON.stringify(ctx.request.body) });\n  ctx.body = await res.json();\n});\n"),
 ("path-traversal", "src/routes/files.js", _EXPRESS + "router.get('/files/:name', (req, res) => {\n  const full = path.join(UPLOADS, req.params.name);\n  res.sendFile(full);\n});\n",
  _EXPRESS + "router.get('/files/:name', (req, res) => {\n  res.sendFile(req.params.name, { root: UPLOADS });\n});\n"),
 ("path-traversal", "src/routes/files.ts", _EXPRESS + "router.get('/logs', async (req, res) => {\n  const file = req.query.file as string;\n  res.send(await fs.readFile(path.join(LOG_DIR, file), 'utf8'));\n});\n",
  _EXPRESS + "router.get('/logs', async (req, res) => {\n  const file = path.resolve(LOG_DIR, String(req.query.file));\n  if (!file.startsWith(LOG_DIR + path.sep)) return res.sendStatus(400);\n  res.send(await fs.readFile(file, 'utf8'));\n});\n"),
 ("xss-sink", "src/routes/hello.js", _EXPRESS + "router.get('/hello', (req, res) => {\n  const who = req.query.name;\n  res.send(`<p>Hello, ${who}</p>`);\n});\n",
  _EXPRESS + "router.get('/hello', (req, res) => {\n  const who = req.query.name;\n  res.send(`<p>Hello, ${escapeHtml(who)}</p>`);\n});\n"),
 ("xss-sink", "src/routes/hello.js", _EXPRESS + "router.get('/hello', (req, res) => {\n  res.send('<p>Hi ' + req.query.name + '</p>');\n});\n",
  _EXPRESS + "router.get('/hello', async (req, res) => {\n  const user = await User.findById(req.session.userId);\n  res.json({ greeting: 'Hi ' + user.name });\n});\n"),
 ("xss-sink", "src/Bio.tsx", "export function Bio({ text }) {\n  const html = marked.parse(text);\n  return <div dangerouslySetInnerHTML={{ __html: html }} />;\n}\n",
  "function toHtml(text) {\n  return DOMPurify.sanitize(marked.parse(text));\n}\nexport function Bio({ text }) {\n  const html = toHtml(text);\n  return <div dangerouslySetInnerHTML={{ __html: html }} />;\n}\n"),
 ("shell-injection", "src/tools/convert.js", "const { exec } = require('child_process');\nconst run = util.promisify(exec);\nasync function convert(input) {\n  await run(`convert ${input} out.png`);\n}\n",
  "const { execFile } = require('child_process');\nconst run = util.promisify(execFile);\nasync function convert(input) {\n  await run('convert', [input, 'out.png']);\n}\n"),
 ("shell-injection", "src/tools/git.ts", "import { exec } from 'node:child_process';\nfunction sh(command: string) {\n  return new Promise((ok, fail) => exec(command, (e, out) => (e ? fail(e) : ok(out))));\n}\n"
  "export const log = (ref: string) => sh('git log ' + ref);\n",
  "import { exec } from 'node:child_process';\nfunction sh(command: string) {\n  return new Promise((ok, fail) => exec(command, (e, out) => (e ? fail(e) : ok(out))));\n}\nexport const status = () => sh('git status --short');\n"),
 ("owner-from-request", "src/routes/notes.js", _EXPRESS + "router.delete('/:id', requireUser, async (req, res) => {\n  const note = await Note.findById(req.params.id);\n  if (note.ownerId !== req.body.ownerId) return res.sendStatus(403);\n  await note.deleteOne();\n  res.sendStatus(204);\n});\n",
  _EXPRESS + "router.delete('/:id', requireUser, async (req, res) => {\n  const note = await Note.findById(req.params.id);\n  if (note.ownerId !== req.user.id) return res.sendStatus(403);\n  await note.deleteOne();\n  res.sendStatus(204);\n});\n"),
 ("object-not-scoped", "src/routes/projects.ts", _EXPRESS + "router.patch('/:id', requireUser, async (req, res) => {\n  const project = await prisma.project.update({ where: { id: req.params.id }, data: { name: req.body.name, editedBy: req.user.id } });\n  res.json(project);\n});\n",
  _EXPRESS + "router.patch('/:id', requireUser, async (req, res) => {\n  const { count } = await prisma.project.updateMany({ where: { id: req.params.id, ownerId: req.user.id }, data: { name: req.body.name } });\n  res.sendStatus(count ? 204 : 404);\n});\n"),
 ("object-not-scoped", "src/routes/invoices.js", _EXPRESS + "router.use(requireUser);\nrouter.get('/', (req, res) => db('invoices').where({ account_id: req.user.accountId }).then((rows) => res.json(rows)));\n"
  "router.delete('/:id', async (req, res) => {\n  await db('invoices').where({ id: req.params.id }).del();\n  res.sendStatus(204);\n});\n",
  _EXPRESS + "router.use(requireUser, requireRole('admin'));\nrouter.delete('/:id', async (req, res) => {\n  await db('invoices').where({ id: req.params.id }).del();\n  audit(req.user.id, 'invoice.deleted');\n  res.sendStatus(204);\n});\n"),
 ("cache-reads-user", "src/reports.service.ts", "export class Reports {\n  async summary(accountId: string, month: string) {\n    const key = `summary:${month}`;\n    const hit = await this.cache.get(key);\n    if (hit) return hit;\n"
  "    const rows = await this.db.query('select * from usage where account_id = $1', [accountId]);\n    await this.cache.set(key, rows);\n    return rows;\n  }\n}\n",
  "export class Reports {\n  async summary(accountId: string, month: string) {\n    const key = `summary:${accountId}:${month}`;\n    const hit = await this.cache.get(key);\n    if (hit) return hit;\n"
  "    const rows = await this.db.query('select * from usage where account_id = $1', [accountId]);\n    await this.cache.set(key, rows);\n    return rows;\n  }\n}\n"),
 ("disabled-control", "src/server.js", "app.use(session({ secret: process.env.SESSION_SECRET, cookie: { secure: true, sameSite: 'none' } }));\napp.post('/transfer', requireUser, transfer);\n",
  "app.use(session({ secret: process.env.SESSION_SECRET, cookie: { secure: true, sameSite: 'none' } }));\napp.post('/transfer', requireUser, csrfProtection, transfer);\n"),
 ("permissive-cors", "src/main.ts", "app.enableCors({\n  origin: (origin, done) => done(null, true),\n  credentials: true,\n});\n",
  "app.enableCors({\n  origin: (origin, done) => done(null, TRUSTED.includes(origin)),\n  credentials: true,\n});\n"),
 ("permissive-cors", "src/cors.js", "app.use((req, res, next) => {\n  res.setHeader('Access-Control-Allow-Origin', req.headers.origin);\n  res.setHeader('Access-Control-Allow-Credentials', 'true');\n  next();\n});\n",
  "app.use((req, res, next) => {\n  if (TRUSTED.has(req.headers.origin)) {\n    res.setHeader('Access-Control-Allow-Origin', req.headers.origin);\n    res.setHeader('Access-Control-Allow-Credentials', 'true');\n  }\n  next();\n});\n"),
 ("key-in-source", "src/vault.ts", "const SECRET_BOX = Buffer.from('k7Qp2Lx9Vb4Nm8Rt1Zc6Hy3Wd5Fg0Js2', 'utf8');\nexport const seal = (iv: Buffer) => createCipheriv('aes-256-gcm', SECRET_BOX, iv);\n",
  "const SECRET_BOX = Buffer.from(process.env.VAULT_KEY ?? '', 'base64');\nexport const seal = (iv: Buffer) => createCipheriv('aes-256-gcm', SECRET_BOX, iv);\n"),
 ("webhook-unverified", "src/routes/billing.js", _EXPRESS + "router.post('/billing/webhook', express.json(), async (req, res) => {\n  await applyEvent(req.body);\n  res.sendStatus(200);\n});\n",
  _EXPRESS + "router.post('/billing/webhook', express.raw({ type: '*/*' }), async (req, res) => {\n  const event = stripe.webhooks.constructEvent(req.body, req.get('stripe-signature'), SIGNING_SECRET);\n  await applyEvent(event);\n  res.sendStatus(200);\n});\n"),
 ("webhook-unverified", "src/hooks.js", "app.post('/hooks/ci', (req, res) => {\n  const sig = req.get('x-ci-signature');\n  if (sig && !validSignature(req.rawBody, sig)) return res.sendStatus(401);\n  queue.push(req.body);\n  res.sendStatus(202);\n});\n",
  "app.post('/hooks/ci', (req, res) => {\n  const sig = req.get('x-ci-signature');\n  if (!sig || !validSignature(req.rawBody, sig)) return res.sendStatus(401);\n  queue.push(req.body);\n  res.sendStatus(202);\n});\n"),
 ("upload-no-limit", "src/routes/avatars.js", "const upload = multer({ dest: 'tmp/' });\nrouter.post('/avatar', upload.single('image'), saveAvatar);\n",
  "const upload = multer({ dest: 'tmp/', limits: { fileSize: 2 * 1024 * 1024, files: 1 } });\nrouter.post('/avatar', upload.single('image'), saveAvatar);\n"),
 ("error-details-exposed", "src/errors.ts", "export const onError = (err, req, res, next) => {\n  res.status(500).json({\n    message: err.message,\n    trace: err.stack,\n  });\n};\n",
  "export const onError = (err, req, res, next) => {\n  res.status(500).json({\n    message: 'Internal error',\n    trace: process.env.NODE_ENV === 'development' ? err.stack : undefined,\n  });\n};\n"),
 ("insecure-random", "src/auth/reset.ts", "export function makeResetToken(): string {\n  const left = Math.random().toString(36).slice(2);\n  return left + Date.now().toString(36);\n}\n",
  "export function pickColor(): string {\n  const hue = Math.floor(Math.random() * 360);\n  return `hsl(${hue}, 70%, 50%)`;\n}\n"),
 ("prototype-pollution", "src/util/assign.js", "function assignDeep(into, from) {\n  Object.keys(from).forEach((k) => {\n    if (typeof from[k] === 'object') {\n      into[k] = into[k] || {};\n      assignDeep(into[k], from[k]);\n    } else {\n      into[k] = from[k];\n    }\n  });\n  return into;\n}\n",
  "function assignDeep(into, from) {\n  Object.keys(from).forEach((k) => {\n    if (k === '__proto__' || k === 'constructor') return;\n    if (typeof from[k] === 'object') {\n      into[k] = into[k] || {};\n      assignDeep(into[k], from[k]);\n    } else {\n      into[k] = from[k];\n    }\n  });\n  return into;\n}\n"),
 ("prototype-pollution", "src/util/dotted.ts", "export function put(target: any, dotted: string, value: unknown) {\n  const keys = dotted.split('.');\n  let node = target;\n  for (const key of keys.slice(0, -1)) {\n    node[key] ??= {};\n    node = node[key];\n  }\n  node[keys[keys.length - 1]] = value;\n}\n",
  "export function lines(text: string) {\n  const rows = text.split('\\n');\n  let row = rows[0];\n  for (let i = 1; i < rows.length; i++) {\n    rows[i] = rows[i].trim();\n    row = row[0];\n  }\n  return rows;\n}\n"),
 ("lost-update", "src/wallet.ts", "export async function topUp(id: string, cents: number) {\n  const wallet = await Wallet.findById(id);\n  wallet.balance += cents;\n  await wallet.save();\n}\n",
  "export async function topUp(id: string, cents: number) {\n  await Wallet.updateOne({ _id: id }, { $inc: { balance: cents } });\n}\n"),
 ("lost-update", "src/quota.js", "async function spend(kv, user, n) {\n  const raw = await kv.get(`quota:${user}`);\n  const quota = JSON.parse(raw);\n  quota.used += n;\n  await kv.set(`quota:${user}`, JSON.stringify(quota));\n}\n",
  "async function spend(kv, user, n) {\n  await kv.incrby(`quota:${user}:used`, n);\n}\n"),
 ("lost-update", "src/seats.ts", "const seats = new Map();\nexport async function book(id: string) {\n  const show = seats.get(id);\n  if (show.left <= 0) throw new Error('full');\n  await reserveWithVenue(id);\n  show.left -= 1;\n}\n",
  "const seats = new Map();\nexport async function book(id: string) {\n  const show = seats.get(id);\n  if (show.left <= 0) throw new Error('full');\n  show.left -= 1;\n  await reserveWithVenue(id);\n}\n"),
 ("check-then-insert", "src/follow.ts", "export async function follow(a: string, b: string) {\n  const found = await prisma.follow.findFirst({ where: { a, b } });\n  if (found) return found;\n  return prisma.follow.create({ data: { a, b } });\n}\n",
  "export async function follow(a: string, b: string) {\n  return prisma.follow.upsert({ where: { a_b: { a, b } }, create: { a, b }, update: {} });\n}\n"),
 ("retry-not-idempotent", "src/payments.ts", "export async function charge(body: object) {\n  for (let attempt = 1; attempt <= 3; attempt++) {\n    try {\n      return await fetch(PAY_URL, { method: 'POST', body: JSON.stringify(body) });\n    } catch (e) {\n      await sleep(500 * attempt);\n    }\n  }\n}\n",
  "export async function charge(body: object, key: string) {\n  for (let attempt = 1; attempt <= 3; attempt++) {\n    try {\n      return await fetch(PAY_URL, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(body) });\n    } catch (e) {\n      await sleep(500 * attempt);\n    }\n  }\n}\n"),
 ("retry-not-idempotent", "src/client.ts", "const api = axios.create({ baseURL: URL });\naxiosRetry(api, { retries: 3, retryCondition: (e) => !e.response || e.response.status >= 500 });\nexport const send = (m) => api.post('/messages', m);\n",
  "const api = axios.create({ baseURL: URL });\naxiosRetry(api, { retries: 3 });\nexport const send = (m) => api.post('/messages', m);\n"),
 ("nonatomic-state-write", "src/progress.js", "const STATE_FILE = path.join(DATA, 'progress.json');\nexport function load() {\n  return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));\n}\nexport function save(state) {\n  fs.writeFileSync(STATE_FILE, JSON.stringify(state));\n}\n",
  "const STATE_FILE = path.join(DATA, 'progress.json');\nexport function load() {\n  return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));\n}\nexport function save(state) {\n  fs.writeFileSync(STATE_FILE + '.tmp', JSON.stringify(state));\n  fs.renameSync(STATE_FILE + '.tmp', STATE_FILE);\n}\n"),
 ("ack-before-durable", "src/ingest.js", "const out = fs.createWriteStream('events.log', { flags: 'a' });\napp.post('/events', (req, res) => {\n  out.write(JSON.stringify(req.body) + '\\n');\n  res.status(201).json({ stored: true });\n});\n",
  "const out = fs.createWriteStream('events.log', { flags: 'a' });\napp.post('/events', (req, res, next) => {\n  out.write(JSON.stringify(req.body) + '\\n', (err) => (err ? next(err) : res.status(201).json({ stored: true })));\n});\n"),
 ("ack-before-durable", "src/db.ts", "export const orders = client.db('shop').collection('orders', { writeConcern: { w: 0 } });\n",
  "export const orders = client.db('shop').collection('orders', { writeConcern: { w: 'majority' } });\n"),
 ("ack-before-effect", "src/worker.ts", "export async function drain(batch: Message[]) {\n  for (const msg of batch) {\n    await channel.ack(msg);\n    await processJob(JSON.parse(msg.content.toString()));\n  }\n}\n",
  "export async function drain(batch: Message[]) {\n  for (const msg of batch) {\n    await processJob(JSON.parse(msg.content.toString()));\n    await channel.ack(msg);\n  }\n}\n"),
 ("ack-before-effect", "src/consumer.js", "const buffer = [];\nawait consumer.run({\n  eachMessage: async ({ message }) => {\n    buffer.push(JSON.parse(message.value));\n  },\n});\n",
  "await consumer.run({\n  eachMessage: async ({ message }) => {\n    await store.insert(JSON.parse(message.value));\n  },\n});\n"),
 ("ack-before-effect", "src/amqp.js", "channel.consume('jobs', handle, { noAck: true });\n", "channel.consume('jobs', handle, { noAck: false });\n"),
 # Under a file-wide auth, role checks are compared like with like: the same kind of change to the same resource.
 ("missing-auth", "src/routes/teams.js", _EXPRESS + "router.use(requireUser);\nrouter.get('/', listTeams);\nrouter.put('/:id', requirePermission('teams:edit'), replaceTeam);\nrouter.delete('/:id', requirePermission('teams:delete'), deleteTeam);\nrouter.patch('/:id', renameTeam);\n",
  _EXPRESS + "router.use(requireUser);\nrouter.get('/', listTeams);\nrouter.post('/', createTeam);\nrouter.put('/:id', requirePermission('teams:edit'), replaceTeam);\nrouter.delete('/:id', requirePermission('teams:delete'), deleteTeam);\n"),
 ("missing-auth", "src/routes/members.js", _EXPRESS + "router.use(requireUser);\nrouter.get('/', listMembers);\nrouter.post('/', requireRole('owner'), invite);\nrouter.delete('/:id', requireRole('owner'), removeMember);\nrouter.patch('/:id/role', changeRole);\n",
  _EXPRESS + "router.use(requireUser);\nrouter.get('/', listMembers);\nrouter.post('/', requireRole('owner'), invite);\nrouter.delete('/:id', requireRole('owner'), removeMember);\nrouter.patch('/:id/role', requireRole('owner'), changeRole);\n"),
 ("missing-auth", "src/teams.controller.ts", "@Controller('teams')\n@UseGuards(JwtGuard, RolesGuard)\nexport class TeamsController {\n  @Get()\n  list() { return this.teams.list(); }\n"
  "  @Put(':id')\n  @Roles('admin')\n  replace(@Param('id') id: string, @Body() dto: Team) { return this.teams.replace(id, dto); }\n  @Delete(':id')\n  @Roles('admin')\n  remove(@Param('id') id: string) { return this.teams.remove(id); }\n"
  "  @Patch(':id')\n  rename(@Param('id') id: string, @Body() dto: Rename) { return this.teams.rename(id, dto); }\n}\n",
  "@Controller('teams')\n@UseGuards(JwtGuard, RolesGuard)\nexport class TeamsController {\n  @Get()\n  list() { return this.teams.list(); }\n  @Get(':id')\n  one(@Param('id') id: string) { return this.teams.one(id); }\n"
  "  @Post('me/avatar')\n  avatar(@CurrentUser() user, @Body() dto: Avatar) { return this.teams.avatar(user.id, dto); }\n"
  "  @Put(':id')\n  @Roles('admin')\n  replace(@Param('id') id: string, @Body() dto: Team) { return this.teams.replace(id, dto); }\n  @Delete(':id')\n  @Roles('admin')\n  remove(@Param('id') id: string) { return this.teams.remove(id); }\n}\n"),
 # From the third review of these rules (rv3 js2 to js5): its false findings as near misses, and its sinks that must keep firing.
 ("missing-auth", "src/auth/auth.controller.ts", "@Controller('accounts')\nexport class AccountsController {\n  @Get()\n  list() { return this.accounts.list(); }\n"
  "  @UseGuards(AdminGuard)\n  @Put(':id')\n  replace(@Param('id') id: string, @Body() dto: Account) { return this.accounts.replace(id, dto); }\n"
  "  @UseGuards(AdminGuard)\n  @Delete(':id')\n  remove(@Param('id') id: string) { return this.accounts.remove(id); }\n"
  "  @Patch(':id')\n  suspend(@Param('id') id: string) { return this.accounts.suspend(id); }\n}\n",
  "@Controller('auth')\nexport class AuthController {\n  @Post('login')\n  login(@Body() dto: LoginDto) { return this.auth.login(dto); }\n  @Post('register')\n  register(@Body() dto: RegisterDto) { return this.auth.register(dto); }\n"
  "  @UseGuards(JwtAuthGuard)\n  @Get('profile')\n  profile(@Req() req) { return req.user; }\n  @UseGuards(JwtAuthGuard)\n  @Post('logout')\n  logout(@Req() req) { return this.auth.logout(req.user.id); }\n"
  "  @UseGuards(JwtAuthGuard)\n  @Post('change-password')\n  changePassword(@Req() req, @Body() dto: Pw) { return this.auth.change(req.user.id, dto); }\n}\n"),
 ("insecure-random", "src/lib/session.ts", "export function newSessionId(): string {\n  const id = Math.random().toString(36).slice(2);\n  return `s_${id}`;\n}\n",
  "export function scheduleSessionRefresh(cb: () => void) {\n  setTimeout(cb, 60000 + Math.random() * 5000);\n}\nexport function sessionColor(id: string) {\n  const palette = ['red', 'blue', 'green'];\n"
  "  return palette[Math.floor(Math.random() * palette.length)];\n}\nexport function shuffleTokens<T>(tokens: T[]): T[] {\n  const a = [...tokens];\n  for (let i = a.length - 1; i > 0; i--) {\n"
  "    const j = Math.floor(Math.random() * (i + 1));\n    [a[i], a[j]] = [a[j], a[i]];\n  }\n  return a;\n}\n"),
 ("shell-injection", "src/run.js", "const { exec } = require('child_process');\nconst run = (command) => new Promise((ok, fail) => exec(command, (e, out) => (e ? fail(e) : ok(out))));\n"
  "app.post('/convert', async (req, res) => {\n  const cmd = `convert ${req.body.file} out.png`;\n  await run(cmd);\n  res.sendStatus(204);\n});\n",
  "const { execFile } = require('child_process');\napp.post('/run', async (req, res) => {\n  const { stdout } = await runCmd('ls', ['-la', req.body.dir]);\n  res.json({ stdout });\n});\n"),
 ("ssrf", "src/a.js", "app.get('/p', async (req, res) => {\n  const r = await fetch(req.query.url);\n  r.body.pipe(res);\n});\n",
  "const ALLOWED = new Set(['https://a.example.com']);\napp.get('/img', async (req, res) => {\n  const target = new URL(req.query.url);\n  if (!ALLOWED.has(target.origin)) return res.status(400).end();\n"
  "  const r = await fetch(target);\n  r.body.pipe(res);\n});\napp.get('/search', async (req, res) => {\n  const q = req.query.q;\n  const url = `https://api.example.com/search?q=${encodeURIComponent(q)}`;\n  res.json(await (await fetch(url)).json());\n});\n"),
 ("path-traversal", "src/a.js", "app.get('/p/:file', (req, res) => {\n  res.sendFile(req.params.file);\n});\n",
  "app.get('/download/:file', (req, res) => {\n  const file = path.resolve(UPLOADS, req.params.file);\n  if (!file.startsWith(UPLOADS + path.sep)) return res.status(400).end();\n  res.download(file);\n});\n"
  "app.get('/avatar/:name', (req, res) => {\n  const name = path.basename(req.params.name);\n  res.sendFile(name, { root: path.join(__dirname, 'avatars') });\n});\n"),
 ("xss-sink", "src/a.js", "app.get('/p', (req, res) => {\n  res.send(`<p>${req.query.name}</p>`);\n});\n",
  "app.get('/report', (req, res) => {\n  const page = parseInt(req.query.page, 10) || 1;\n  res.send(`<h1>Page ${page}</h1>`);\n});\napp.get('/hello', (req, res) => {\n  const name = req.query.name;\n"
  "  res.send('<p>Hello ' + escapeHtml(name) + '</p>');\n});\napp.get('/greet', (req, res) => res.render('greet', { name: req.query.name }));\n"),
 ("xss-sink", "src/b.vue", "<template><div v-html=\"body\"></div></template>\n<script>export default { props: ['body'] }</script>\n",
  "<template><div>{{ body }}</div></template>\n<script>export default { props: ['body'] }</script>\n"),
 ("xss-sink", "src/c.svelte", "<script>export let body;</script>\n{@html body}\n", "<script>export let body;</script>\n<p>{body}</p>\n"),
 ("object-not-scoped", "src/routes/items.js", _EXPRESS + "router.use(requireUser);\nrouter.delete('/items/:id', async (req, res) => {\n  await db.item.delete({ where: { id: req.params.id } });\n  audit(req.user.id);\n  res.sendStatus(204);\n});\n",
  _EXPRESS + "router.patch('/items/:id', async (req, res) => {\n  const { id } = req.params;\n  const userId = req.user.id;\n  const existing = await db.item.findFirst({ where: { id, ownerId: userId } });\n"
  "  if (!existing) return res.status(404).end();\n  res.json(await db.item.update({ where: { id }, data: { name: req.body.name } }));\n});\n"
  "router.delete('/posts/:id', async (req, res) => {\n  const post = await Post.findById(req.params.id);\n  if (!post || String(post.author) !== String(req.user.id)) return res.sendStatus(404);\n"
  "  await Post.deleteOne({ _id: req.params.id });\n  res.sendStatus(204);\n});\n"),
 ("object-not-scoped", "app/api/users/[id]/route.ts", "export async function DELETE(request: Request, { params }: { params: { id: string } }) {\n  const session = await getServerSession();\n"
  "  if (!session) return NextResponse.json({ error: 'unauthorized' }, { status: 401 });\n  await prisma.user.delete({ where: { id: params.id } });\n  return NextResponse.json({ ok: true });\n}\n",
  "export async function DELETE(request: Request, { params }: { params: { id: string } }) {\n  const session = await getServerSession();\n"
  "  if (!session || session.user.id !== params.id) return NextResponse.json({ error: 'forbidden' }, { status: 403 });\n  await prisma.user.delete({ where: { id: params.id } });\n  return NextResponse.json({ ok: true });\n}\n"),
 ("cache-reads-user", "src/users/users.service.ts", "export class UsersService {\n  async getTenantSettings(tenantId: string) {\n    return this.cache.get(`settings`) ?? this.load(tenantId);\n  }\n}\n",
  "export class UsersService {\n  async getProfile(userId: string) {\n    const key = `profile:${userId}`;\n    return this.cache.wrap(key, () => this.users.findOneBy({ id: userId }));\n  }\n}\n"),
 ("webhook-unverified", "src/webhooks/stripe.js", "const app = express.Router();\napp.post('/stripe', express.json(), (req, res) => {\n  handle(req.body);\n  res.json({ received: true });\n});\n",
  "const app = express.Router();\napp.post('/stripe', express.raw({ type: 'application/json' }), (req, res) => {\n"
  "  const event = stripe.webhooks.constructEvent(req.body, req.headers['stripe-signature'], process.env.WH_SECRET);\n  res.json({ received: true });\n});\n"),
 ("prototype-pollution", "src/util.js", "function merge(target, source) {\n  for (const key of Object.keys(source)) {\n    if (typeof source[key] === 'object') {\n      target[key] = target[key] || {};\n"
  "      merge(target[key], source[key]);\n    } else {\n      target[key] = source[key];\n    }\n  }\n  return target;\n}\n",
  "function get(obj, path) {\n  let cur = obj;\n  for (const part of path.split('.')) {\n    cur = cur[part];\n  }\n  return cur;\n}\nconst counts = {};\nfunction tally(words) {\n"
  "  for (const w of words.split(' ')) {\n    counts[w] = (counts[w] || 0) + 1;\n  }\n}\n"),
]
JS_CASES = [*JS_CASES, *JS_RECALL_CASES]
