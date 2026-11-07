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
]
