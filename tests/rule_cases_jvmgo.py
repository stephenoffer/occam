"""Checks in rules_go.py and rules_jvm.py, each as (rule, path, what should fire, its near miss). test_scanner_rules.py runs them with the rest,
and test_rules_jvmgo.py checks none sends an agent back and each stays fast on hostile input. Team jvmgo."""

_GO_HANDLER = "package api\n\nimport (\n\t\"net/http\"\n)\n\n"
_GO_STORE = "package store\n\n"


def _go(body: str, head: str = _GO_STORE) -> str:
    return head + body


# A switch stops at the first true case, so after the error case `case !ok` never runs and the handler is reached.
_INTERCEPTOR = ("func (a *Authz) Unary(ctx context.Context, req any, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (any, error) {\n"
                "\tok, err := a.policy.Allowed(ctx, info.FullMethod)\n"
                "\tswitch {\n\tcase err != nil:\n\t\ta.log.Warn(\"policy check failed\", \"err\", err)\n{tail}"
                "\tcase !ok:\n\t\treturn nil, status.Error(codes.PermissionDenied, \"denied\")\n\t}\n"
                "\treturn handler(ctx, req)\n}\n")
_ROUTES = ("func routes(r *gin.Engine) {\n\tv1 := r.Group(\"/v1\", auth.Session())\n\tops := v1.Group(\"/admin\", auth.HasRole(\"ops\"))\n"
           "\tops.GET(\"/jobs\", listJobs)\n\tv1.GET(\"/me\", me)\n\t{where}.DELETE(\"{path}\", purgeCache)\n}\n")
_CONTROLLER = ("@RestController\n@RequestMapping(\"/api/billing\")\npublic class InvoiceAdminController {\n"
               "    @GetMapping\n    @PreAuthorize(\"hasRole('BILLING')\")\n    public List<Invoice> all() { return invoices.all(); }\n\n"
               "    @PostMapping(\"/{id}/void\")\n    @PreAuthorize(\"hasRole('BILLING')\")\n    public void voidIt(@PathVariable long id) { invoices.voidInvoice(id); }\n\n"
               "    @PostMapping(\"/{id}/refund\")\n{guard}    public void refund(@PathVariable long id) { invoices.refund(id); }\n}\n")
_ACCOUNTS = ("@Service\npublic class WalletService {\n    private final WalletRepository wallets;\n\n"
             "    @Transactional\n    public void credit(long id, BigDecimal amount) {\n"
             "        Wallet wallet = wallets.{finder}(id).orElseThrow();\n"
             "        wallet.setFunds(wallet.getFunds().add(amount));\n        wallets.save(wallet);\n    }\n}\n")

JVMGO_CASES = [
    # Go: SQL built before the call, through a variable or a builder
    ("sql-injection", "store/users.go", _go("func (s *Store) ByName(ctx context.Context, name string) error {\n\tq := fmt.Sprintf(\"SELECT id FROM users WHERE name = '%s'\", name)\n"
                                            "\t_, err := s.db.QueryContext(ctx, q)\n\treturn err\n}\n"),
     _go("func (s *Store) Purge(ctx context.Context, ids []int64) error {\n\tmarks := make([]string, len(ids))\n\targs := make([]any, len(ids))\n"
         "\tfor i, id := range ids {\n\t\tmarks[i] = fmt.Sprintf(\"$%d\", i+1)\n\t\targs[i] = id\n\t}\n"
         "\tq := fmt.Sprintf(\"DELETE FROM users WHERE id IN (%s)\", strings.Join(marks, \",\"))\n\t_, err := s.db.ExecContext(ctx, q, args...)\n\treturn err\n}\n")),
    ("sql-injection", "store/items.go", _go("func list(db *sql.DB, column string) {\n\tvar b strings.Builder\n\tb.WriteString(\"SELECT id FROM items ORDER BY \")\n"
                                            "\tb.WriteString(column)\n\tdb.Query(b.String())\n}\n"),
     _go("func list(db *sql.DB) {\n\tvar b strings.Builder\n\tb.WriteString(\"SELECT id FROM items ORDER BY created_at\")\n\tdb.Query(b.String())\n}\n")),
    ("sql-injection", "store/tags.go", _go("func tagged(db *sql.DB, tags []string) {\n\tquoted := []string{}\n\tfor _, t := range tags {\n"
                                           "\t\tquoted = append(quoted, \"'\"+t+\"'\")\n\t}\n"
                                           "\tq := \"SELECT id FROM posts WHERE tag IN (\" + strings.Join(quoted, \",\") + \")\"\n\tdb.Query(q)\n}\n"),
     _go("func tagged(db *sql.DB, tags []string) {\n\tconst q = \"SELECT id FROM posts WHERE tag = ANY($1)\"\n\tdb.Query(q, pq.Array(tags))\n}\n")),
    # Go: a shell command line built at runtime
    ("shell-injection", "ops/ping.go", _go("func ping(ctx context.Context, host string) error {\n\tline := \"ping -c 1 \" + host\n"
                                           "\treturn exec.CommandContext(ctx, \"sh\", \"-c\", line).Run()\n}\n"),
     _go("func count(ctx context.Context) error {\n\treturn exec.CommandContext(ctx, \"sh\", \"-c\", \"ls -l | wc -l\").Run()\n}\n")),
    ("shell-injection", "ops/tar.go", _go("func pack(dir string) error {\n\treturn exec.Command(\"bash\", \"-c\", fmt.Sprintf(\"tar czf out.tgz %s\", dir)).Run()\n}\n"),
     _go("func pack(dir string) error {\n\treturn exec.Command(\"tar\", \"czf\", \"out.tgz\", \"--\", dir).Run()\n}\n")),
    # Go: archive entry names joined onto a folder
    ("unsafe-extract", "unpack/tar.go", "package unpack\n\nimport \"archive/tar\"\n\nfunc place(h *tar.Header, dst string) (*os.File, error) {\n"
                                        "\tout := filepath.Join(dst, h.Name)\n\treturn os.Create(out)\n}\n",
     "package unpack\n\nimport \"archive/tar\"\n\nfunc place(h *tar.Header, dst string) (*os.File, error) {\n\tif !filepath.IsLocal(h.Name) {\n"
     "\t\treturn nil, errBadName\n\t}\n\tout := filepath.Join(dst, h.Name)\n\treturn os.Create(out)\n}\n"),
    # Go: a URL the request chose, fetched with the default client
    ("ssrf", "api/preview.go", _go("func preview(w http.ResponseWriter, r *http.Request) {\n\ttarget := r.URL.Query().Get(\"link\")\n\tresp, err := http.Get(target)\n"
                                   "\tif err != nil {\n\t\treturn\n\t}\n\tdefer resp.Body.Close()\n}\n", _GO_HANDLER),
     _go("func preview(w http.ResponseWriter, r *http.Request) {\n\ttarget := r.URL.Query().Get(\"link\")\n\tu, err := url.Parse(target)\n"
         "\tif err != nil || !allowedHosts[u.Hostname()] {\n\t\treturn\n\t}\n\tresp, _ := http.Get(u.String())\n\tdefer resp.Body.Close()\n}\n", _GO_HANDLER)),
    # Go: CORS
    ("permissive-cors", "api/cors.go", _go("func allow(w http.ResponseWriter, origin string) {\n\tif strings.HasSuffix(origin, \"shop.example\") {\n"
                                           "\t\tw.Header().Set(\"Access-Control-Allow-Origin\", origin)\n\t}\n}\n", _GO_HANDLER),
     _go("func allow(w http.ResponseWriter, u *url.URL, origin string) {\n\tif u.Scheme == \"https\" && strings.HasSuffix(u.Hostname(), \".shop.example\") {\n"
         "\t\tw.Header().Set(\"Access-Control-Allow-Origin\", origin)\n\t}\n}\n", _GO_HANDLER)),
    ("permissive-cors", "api/cors.go", _go("var c = cors.Config{\n\tAllowOriginFunc:  func(origin string) bool { return true },\n\tAllowCredentials: true,\n}\n"),
     _go("var c = cors.Config{\n\tAllowOriginFunc:  func(origin string) bool { return trusted[origin] },\n\tAllowCredentials: true,\n}\n")),
    # Go: what an error response or a log line carries
    ("error-details-exposed", "api/report.go", _go("func open(w http.ResponseWriter, dsn string) {\n\tif _, err := sql.Open(\"pgx\", dsn); err != nil {\n"
                                                   "\t\thttp.Error(w, \"cannot reach \"+dsn, http.StatusServiceUnavailable)\n\t}\n}\n", _GO_HANDLER),
     _go("func open(w http.ResponseWriter, dsn, host string) {\n\tif _, err := sql.Open(\"pgx\", dsn); err != nil {\n\t\tlog.Printf(\"cannot reach %s: %v\", host, err)\n"
         "\t\thttp.Error(w, \"reports are unavailable\", http.StatusServiceUnavailable)\n\t}\n}\n", _GO_HANDLER)),
    ("sensitive-log", "cmd/api/main.go", "package main\n\nfunc main() {\n\tcfg := config.MustLoad()\n\tlog.Printf(\"loaded settings %+v\", cfg)\n}\n",
     "package main\n\nfunc main() {\n\tcfg := config.MustLoad()\n\tlog.Printf(\"listening on %v\", cfg.Addr)\n}\n"),
    # Go: an authorization check that lets the request through when it errors
    ("fail-open", "authz/unary.go", _go(_INTERCEPTOR.replace("{tail}", "")),
     _go(_INTERCEPTOR.replace("{tail}", "\t\treturn nil, status.Error(codes.Unavailable, \"try again\")\n"))),
    # Go: math/rand for something that grants access
    ("insecure-random", "auth/reset.go", "package auth\n\nimport \"math/rand\"\n\nfunc resetToken() string {\n\ttoken := strconv.FormatInt(rand.Int63(), 36)\n\treturn token\n}\n",
     "package auth\n\nimport \"math/rand\"\n\nfunc backoff() time.Duration {\n\tjitter := rand.Intn(250)\n\treturn time.Duration(jitter) * time.Millisecond\n}\n"),
    # Go: a request body decoded into live state
    ("mass-assignment", "api/prefs.go", _go("func (s *Server) savePrefs(w http.ResponseWriter, r *http.Request) {\n\tjson.NewDecoder(r.Body).Decode(&s.prefs)\n}\n", _GO_HANDLER),
     _go("func (s *Server) savePrefs(w http.ResponseWriter, r *http.Request) {\n\tvar in prefsInput\n\tjson.NewDecoder(r.Body).Decode(&in)\n"
         "\ts.prefs.Theme = in.Theme\n}\n", _GO_HANDLER)),
    ("mass-assignment", "api/users.go", _go("func update(c *gin.Context) {\n\tvar u models.User\n\tc.ShouldBindJSON(&u)\n\tdb.Save(&u)\n}\n"),
     _go("func update(c *gin.Context) {\n\tvar in models.UserUpdate\n\tc.ShouldBindJSON(&in)\n\tdb.Model(&models.User{}).Updates(map[string]any{\"name\": in.Name})\n}\n")),
    # Go: a package map changed by concurrent handlers
    ("unsynchronized-state", "api/carts.go", _go("var carts = map[string][]string{}\n\nfunc add(w http.ResponseWriter, r *http.Request) {\n"
                                                 "\tcarts[r.FormValue(\"id\")] = append(carts[r.FormValue(\"id\")], r.FormValue(\"sku\"))\n}\n", _GO_HANDLER),
     _go("var (\n\tmu    sync.Mutex\n)\nvar carts = map[string][]string{}\n\nfunc add(w http.ResponseWriter, r *http.Request) {\n\tmu.Lock()\n\tdefer mu.Unlock()\n"
         "\tcarts[r.FormValue(\"id\")] = append(carts[r.FormValue(\"id\")], r.FormValue(\"sku\"))\n}\n", _GO_HANDLER)),
    # Go: data
    ("multi-write-no-transaction", "store/ledger.go", _go("func (s *Store) Move(ctx context.Context, from, to int64, n int) error {\n"
                                                         "\tif _, err := s.db.ExecContext(ctx, \"UPDATE wallets SET n = n - $1 WHERE id = $2\", n, from); err != nil {\n\t\treturn err\n\t}\n"
                                                         "\t_, err := s.db.ExecContext(ctx, \"UPDATE wallets SET n = n + $1 WHERE id = $2\", n, to)\n\treturn err\n}\n"),
     _go("func (s *Store) Move(ctx context.Context, from, to int64, n int) error {\n\ttx, err := s.db.BeginTx(ctx, nil)\n\tif err != nil {\n\t\treturn err\n\t}\n"
         "\tdefer tx.Rollback()\n\tif _, err := tx.ExecContext(ctx, \"UPDATE wallets SET n = n - $1 WHERE id = $2\", n, from); err != nil {\n\t\treturn err\n\t}\n"
         "\tif _, err := tx.ExecContext(ctx, \"UPDATE wallets SET n = n + $1 WHERE id = $2\", n, to); err != nil {\n\t\treturn err\n\t}\n\treturn tx.Commit()\n}\n")),
    ("lost-update", "store/seats.go", _go("func (s *Store) Take(ctx context.Context, ev *Event) error {\n\tev.SeatsLeft--\n"
                                          "\t_, err := s.db.ExecContext(ctx, \"UPDATE events SET seats_left = $1 WHERE id = $2\", ev.SeatsLeft, ev.ID)\n\treturn err\n}\n"),
     _go("func (s *Store) Take(ctx context.Context, ev *Event) error {\n\tev.Taken++\n"
         "\t_, err := s.db.ExecContext(ctx, \"UPDATE events SET seats_left = seats_left - 1 WHERE id = $1 AND seats_left > 0\", ev.ID)\n\treturn err\n}\n")),
    ("check-then-insert", "store/slugs.go", _go("type Page struct {\n\tSlug string `gorm:\"size:80;index\"`\n}\n\nfunc (s *Store) Claim(slug string) error {\n"
                                                "\tvar p Page\n\terr := s.db.Where(\"slug = ?\", slug).First(&p).Error\n\tif errors.Is(err, gorm.ErrRecordNotFound) {\n"
                                                "\t\treturn s.db.Create(&Page{Slug: slug}).Error\n\t}\n\treturn errTaken\n}\n"),
     _go("type Page struct {\n\tSlug string `gorm:\"size:80;uniqueIndex\"`\n}\n\nfunc (s *Store) Claim(slug string) error {\n"
         "\tvar p Page\n\terr := s.db.Where(\"slug = ?\", slug).First(&p).Error\n\tif errors.Is(err, gorm.ErrRecordNotFound) {\n"
         "\t\treturn s.db.Create(&Page{Slug: slug}).Error\n\t}\n\treturn errTaken\n}\n")),
    ("retry-not-idempotent", "payouts/client.go", _go("func (c *Client) Pay(ctx context.Context, body []byte) error {\n\treturn retry.Do(func() error {\n"
                                                      "\t\treq, _ := http.NewRequestWithContext(ctx, http.MethodPost, c.url, bytes.NewReader(body))\n"
                                                      "\t\t_, err := c.http.Do(req)\n\t\treturn err\n\t})\n}\n"),
     _go("func (c *Client) Pay(ctx context.Context, body []byte, key string) error {\n\treturn retry.Do(func() error {\n"
         "\t\treq, _ := http.NewRequestWithContext(ctx, http.MethodPost, c.url, bytes.NewReader(body))\n\t\treq.Header.Set(\"Idempotency-Key\", key)\n"
         "\t\t_, err := c.http.Do(req)\n\t\treturn err\n\t})\n}\n")),
    ("checkpoint-before-effect", "sync/push.go", _go("func (j *Job) Step(ctx context.Context, rows []Row, last int64) error {\n"
                                                     "\tif err := j.kv.Set(ctx, cursorKey, last, 0).Err(); err != nil {\n\t\treturn err\n\t}\n"
                                                     "\treturn j.remote.PushRows(ctx, rows)\n}\n"),
     _go("func (j *Job) Step(ctx context.Context, rows []Row, last int64) error {\n\tif err := j.remote.PushRows(ctx, rows); err != nil {\n\t\treturn err\n\t}\n"
         "\treturn j.kv.Set(ctx, cursorKey, last, 0).Err()\n}\n")),
    ("lock-without-fencing", "jobs/leader.go", _go("func (s *S) once(ctx context.Context) {\n\tif ok, _ := s.rdb.SetNX(ctx, jobLock, s.id, time.Minute).Result(); !ok {\n"
                                                   "\t\treturn\n\t}\n\ts.work(ctx)\n\ts.rdb.Del(ctx, jobLock)\n}\n"),
     _go("func (s *S) once(ctx context.Context) {\n\tif ok, _ := s.rdb.SetNX(ctx, jobLock, s.id, time.Minute).Result(); !ok {\n"
         "\t\treturn\n\t}\n\ts.work(ctx)\n\tunlock.Run(ctx, s.rdb, []string{jobLock}, s.id)\n}\n")),
    ("native-type-mismatch", "native/sum.go", "package native\n\nimport \"C\"\n\nfunc Sum(xs []int64) int {\n\treturn int(C.sum((*C.int)(unsafe.Pointer(&xs[0])), C.int(len(xs))))\n}\n",
     "package native\n\nimport \"C\"\n\nfunc Sum(xs []int32) int {\n\treturn int(C.sum((*C.int)(unsafe.Pointer(&xs[0])), C.int(len(xs))))\n}\n"),
    ("unacknowledged-write", "store/mongo.go", _go("func coll(db *mongo.Database) *mongo.Collection {\n\treturn db.Collection(\"orders\", options.Collection().SetWriteConcern(writeconcern.Unacknowledged()))\n}\n"),
     _go("func coll(db *mongo.Database) *mongo.Collection {\n\treturn db.Collection(\"orders\", options.Collection().SetWriteConcern(writeconcern.Majority()))\n}\n")),
    ("live-credential-in-test", "storage/blob_test.go", "package storage\n\nfunc client(t *testing.T) {\n\tcfg, _ := config.LoadDefaultConfig(ctx, config.WithSharedConfigProfile(\"prod-admin\"))\n\t_ = cfg\n}\n",
     "package storage\n\nfunc client(t *testing.T) {\n\tcfg, _ := config.LoadDefaultConfig(ctx, config.WithSharedConfigProfile(\"localstack\"))\n\t_ = cfg\n}\n"),
    ("weak-password-hash", "auth/users.go", _go("func hash(password string) string {\n\tsum := sha256.Sum256([]byte(password))\n\treturn hex.EncodeToString(sum[:])\n}\n"),
     _go("func hash(password string) ([]byte, error) {\n\treturn bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)\n}\n")),
    ("missing-auth", "server/routes.go", _go(_ROUTES.replace("{where}", "v1").replace("{path}", "/admin/cache")),
     _go(_ROUTES.replace("{where}", "ops").replace("{path}", "/cache"))),
    ("webhook-unverified", "hooks/github.go", _go("func (h *H) ok(r *http.Request, body []byte) bool {\n\tts := r.Header.Get(\"X-Hook-Timestamp\")\n"
                                                  "\tmac := hmac.New(sha256.New, h.secret)\n\tmac.Write([]byte(ts + \".\"))\n\tmac.Write(body)\n"
                                                  "\treturn hmac.Equal(mac.Sum(nil), []byte(r.Header.Get(\"X-Hook-Signature\")))\n}\n", _GO_HANDLER),
     _go("func (h *H) ok(r *http.Request, body []byte) bool {\n\tts := r.Header.Get(\"X-Hook-Timestamp\")\n\tsec, _ := strconv.ParseInt(ts, 10, 64)\n"
         "\tif time.Since(time.Unix(sec, 0)).Abs() > 5*time.Minute {\n\t\treturn false\n\t}\n\tmac := hmac.New(sha256.New, h.secret)\n"
         "\tmac.Write([]byte(ts + \".\"))\n\tmac.Write(body)\n\treturn hmac.Equal(mac.Sum(nil), []byte(r.Header.Get(\"X-Hook-Signature\")))\n}\n", _GO_HANDLER)),
    ("nonatomic-state-write", "cache/files.go", _go("func save(path string, data []byte) error {\n\tif _, err := os.Stat(path); err == nil {\n\t\treturn nil\n\t}\n"
                                                    "\treturn os.WriteFile(path, data, 0o644)\n}\n"),
     _go("func save(path string, data []byte) error {\n\tif _, err := os.Stat(path); err == nil {\n\t\treturn nil\n\t}\n"
         "\tif err := os.WriteFile(path+\".part\", data, 0o644); err != nil {\n\t\treturn err\n\t}\n\treturn os.Rename(path+\".part\", path)\n}\n")),
    ("unbounded-upload", "api/upload.go", _go("func upload(w http.ResponseWriter, r *http.Request) {\n\tf, _, err := r.FormFile(\"scan\")\n\tif err != nil {\n\t\treturn\n\t}\n"
                                              "\tdata, _ := io.ReadAll(f)\n\tstore(data)\n}\n", _GO_HANDLER),
     _go("func upload(w http.ResponseWriter, r *http.Request) {\n\tr.Body = http.MaxBytesReader(w, r.Body, 10<<20)\n\tf, _, err := r.FormFile(\"scan\")\n"
         "\tif err != nil {\n\t\treturn\n\t}\n\tdata, _ := io.ReadAll(f)\n\tstore(data)\n}\n", _GO_HANDLER)),

    # Java and Kotlin: SQL
    ("sql-injection", "src/main/java/app/OrderDao.java",
     "class OrderDao {\n    List<Order> find(String sku, String sort) {\n        StringBuilder sql = new StringBuilder(\"SELECT id FROM orders WHERE 1=1\");\n"
     "        sql.append(\" AND sku = '\").append(sku).append(\"'\");\n        sql.append(\" ORDER BY \").append(sort);\n"
     "        return jdbc.query(sql.toString(), MAPPER);\n    }\n}\n",
     "class OrderDao {\n    List<Order> find(String sku, int limit) {\n        StringBuilder sql = new StringBuilder(\"SELECT id FROM orders WHERE 1=1\");\n"
     "        List<Object> args = new ArrayList<>();\n        sql.append(\" AND sku = ?\");\n        args.add(sku);\n        sql.append(\" LIMIT \").append(limit);\n"
     "        return jdbc.query(sql.toString(), MAPPER, args.toArray());\n    }\n}\n"),
    ("sql-injection", "src/main/java/app/Search.java",
     "class Search {\n    List<?> by(String name) {\n        String q = String.format(\"SELECT * FROM people WHERE name = '%s'\", name);\n"
     "        return em.createNativeQuery(q).getResultList();\n    }\n}\n",
     "class Search {\n    List<?> by(String name) {\n        return em.createNativeQuery(\"SELECT * FROM people WHERE name = :name\").setParameter(\"name\", name).getResultList();\n    }\n}\n"),
    ("sql-injection", "src/main/java/app/PeopleMapper.java", "interface PeopleMapper {\n    @Select(\"SELECT * FROM people WHERE name = '${name}'\")\n    List<Person> byName(String name);\n}\n",
     "interface PeopleMapper {\n    @Select(\"SELECT * FROM people WHERE name = #{name}\")\n    List<Person> byName(String name);\n}\n"),
    ("sql-injection", "src/main/kotlin/app/Repo.kt", "class Repo {\n    fun byName(name: String) = jdbc.queryForList(\"SELECT id FROM people WHERE name = '$name'\")\n}\n",
     "class Repo {\n    fun byName(name: String) = jdbc.queryForList(\"SELECT id FROM people WHERE name = ?\", name)\n}\n"),
    # Java: shells, deserialization, TLS, passwords
    ("shell-injection", "src/main/java/app/Convert.java", "class Convert {\n    void run(String file) throws Exception {\n"
                                                          "        new ProcessBuilder(\"bash\", \"-c\", \"convert \" + file + \" out.png\").start();\n    }\n}\n",
     "class Convert {\n    void run(String file) throws Exception {\n        new ProcessBuilder(\"convert\", \"--\", file, \"out.png\").start();\n    }\n}\n"),
    ("shell-injection", "src/main/kotlin/app/Convert.kt", "fun run(file: String) {\n    ProcessBuilder(\"sh\", \"-c\", cmd(file)).start()\n}\n",
     "fun run() {\n    ProcessBuilder(\"sh\", \"-c\", \"ls -l | wc -l\").start()\n}\n"),
    ("unsafe-deserialize", "src/main/java/app/Json.java", "class Json {\n    ObjectMapper mapper() {\n        ObjectMapper m = new ObjectMapper();\n"
                                                         "        m.enableDefaultTyping();\n        return m;\n    }\n}\n",
     "class Json {\n    ObjectMapper mapper() {\n        PolymorphicTypeValidator ptv = BasicPolymorphicTypeValidator.builder().allowIfSubType(\"app.model.\").build();\n"
     "        ObjectMapper m = new ObjectMapper();\n        m.activateDefaultTyping(ptv);\n        return m;\n    }\n}\n"),
    ("tls-disabled", "src/main/java/app/Tls.java", "class Open implements X509TrustManager {\n"
                                                   "    public void checkServerTrusted(X509Certificate[] chain, String type) {\n    }\n}\n",
     "class Pinned implements X509TrustManager {\n    public void checkServerTrusted(X509Certificate[] chain, String type) throws CertificateException {\n"
     "        delegate.checkServerTrusted(chain, type);\n    }\n}\n"),
    ("tls-disabled", "src/main/java/app/Http.java", "class Http {\n    void setup(HttpsURLConnection c) {\n        c.setHostnameVerifier((host, session) -> true);\n    }\n}\n",
     "class Http {\n    void setup(HttpsURLConnection c) {\n        c.setHostnameVerifier(HttpsURLConnection.getDefaultHostnameVerifier());\n    }\n}\n"),
    ("weak-password-hash", "src/main/java/app/Security.java", "class Security {\n    @Bean\n    PasswordEncoder encoder() {\n        return NoOpPasswordEncoder.getInstance();\n    }\n}\n",
     "class Security {\n    @Bean\n    PasswordEncoder encoder() {\n        return new BCryptPasswordEncoder(12);\n    }\n}\n"),
    ("unacknowledged-write", "src/main/java/app/Mongo.java", "class Mongo {\n    void tune(MongoTemplate t) {\n        t.setWriteConcern(WriteConcern.UNACKNOWLEDGED);\n    }\n}\n",
     "class Mongo {\n    void tune(MongoTemplate t) {\n        t.setWriteConcern(WriteConcern.MAJORITY);\n    }\n}\n"),
    # Java: Spring Security settings
    ("disabled-control", "src/main/java/app/WebSecurity.java", "class WebSecurity {\n    SecurityFilterChain chain(HttpSecurity http) throws Exception {\n"
                                                               "        return http.formLogin(Customizer.withDefaults()).csrf(AbstractHttpConfigurer::disable).build();\n    }\n}\n",
     "class WebSecurity {\n    SecurityFilterChain chain(HttpSecurity http) throws Exception {\n        return http.csrf(c -> c.disable())\n"
     "            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))\n            .oauth2ResourceServer(o -> o.jwt(Customizer.withDefaults())).build();\n    }\n}\n"),
    ("permissive-cors", "src/main/java/app/Cors.java", "class Cors implements WebMvcConfigurer {\n    public void addCorsMappings(CorsRegistry r) {\n"
                                                       "        r.addMapping(\"/**\").allowedOriginPatterns(\"*\").allowCredentials(true);\n    }\n}\n",
     "class Cors implements WebMvcConfigurer {\n    public void addCorsMappings(CorsRegistry r) {\n"
     "        r.addMapping(\"/**\").allowedOriginPatterns(\"https://*.shop.example\").allowCredentials(true);\n    }\n}\n"),
    ("permissive-cors", "src/main/java/app/OriginFilter.java", "class OriginFilter {\n    boolean ok(String origin) {\n        // feeds Access-Control-Allow-Origin\n"
                                                               "        return origin.endsWith(\"shop.example\");\n    }\n}\n",
     "class OriginFilter {\n    boolean ok(String origin) {\n        // feeds Access-Control-Allow-Origin\n        return ALLOWED.contains(origin);\n    }\n}\n"),
    # Java: authorization
    ("fail-open", "src/main/java/app/TeamAccess.java", "class TeamAccess {\n    public AuthorizationDecision check(Supplier<Authentication> a, Object ctx) {\n"
                                                       "        try {\n            return new AuthorizationDecision(teams.isMember(a.get().getName()));\n"
                                                       "        } catch (RestClientException e) {\n            return new AuthorizationDecision(true);\n        }\n    }\n}\n",
     "class TeamAccess {\n    public AuthorizationDecision check(Supplier<Authentication> a, Object ctx) {\n"
     "        try {\n            return new AuthorizationDecision(teams.isMember(a.get().getName()));\n"
     "        } catch (RestClientException e) {\n            return new AuthorizationDecision(false);\n        }\n    }\n}\n"),
    ("missing-auth", "src/main/java/app/InvoiceAdminController.java", _CONTROLLER.replace("{guard}", ""),
     _CONTROLLER.replace("{guard}", "    @PreAuthorize(\"hasRole('BILLING')\")\n")),
    # Java: URLs, paths, archives
    ("ssrf", "src/main/java/app/Fetch.java", "class Fetch {\n    @GetMapping(\"/fetch\")\n    String get(@RequestParam String target) {\n"
                                             "        return rest.getForObject(target, String.class);\n    }\n}\n",
     "class Fetch {\n    @GetMapping(\"/fetch\")\n    String get(@RequestParam String target) {\n        URI uri = URI.create(target);\n"
     "        if (!ALLOWED_HOSTS.contains(uri.getHost())) throw new IllegalArgumentException();\n        return rest.getForObject(uri, String.class);\n    }\n}\n"),
    ("weak-path-check", "src/main/java/app/Files.java", "class Downloads {\n    Path open(String name) {\n        Path p = root.resolve(name);\n"
                                                        "        if (!p.startsWith(root)) throw new SecurityException();\n        return p;\n    }\n}\n",
     "class Downloads {\n    Path open(String name) {\n        Path p = root.resolve(name).normalize();\n"
     "        if (!p.startsWith(root)) throw new SecurityException();\n        return p;\n    }\n}\n"),
    ("unsafe-extract", "src/main/java/app/Unzip.java", "class Unzip {\n    void into(ZipInputStream in, File dir) throws IOException {\n        ZipEntry e;\n"
                                                       "        while ((e = in.getNextEntry()) != null && count++ < MAX_ENTRIES) {\n            File out = new File(dir, e.getName());\n"
                                                       "            Files.copy(in, out.toPath());\n        }\n    }\n}\n",
     "class Unzip {\n    void into(ZipInputStream in, Path dir) throws IOException {\n        ZipEntry e;\n"
     "        while ((e = in.getNextEntry()) != null && count++ < MAX_ENTRIES) {\n            Path out = dir.resolve(e.getName()).normalize();\n"
     "            if (!out.startsWith(dir)) throw new IOException(\"bad entry\");\n            Files.copy(in, out);\n        }\n    }\n}\n"),
    ("unbounded-upload", "src/main/java/app/Unzip.java", "class Unzip {\n    void into(ZipInputStream in, Path dir) throws IOException {\n        ZipEntry e;\n"
                                                         "        while ((e = in.getNextEntry()) != null) {\n            Path out = dir.resolve(e.getName()).normalize();\n"
                                                         "            if (!out.startsWith(dir)) throw new IOException(\"bad entry\");\n            Files.copy(in, out);\n        }\n    }\n}\n",
     "class Unzip {\n    void into(ZipInputStream in, Path dir) throws IOException {\n        ZipEntry e;\n"
     "        while ((e = in.getNextEntry()) != null && count++ < MAX_ENTRIES) {\n            Path out = dir.resolve(e.getName()).normalize();\n"
     "            if (!out.startsWith(dir)) throw new IOException(\"bad entry\");\n            Files.copy(new BoundedInputStream(in, MAX_BYTES), out);\n        }\n    }\n}\n"),
    ("webhook-unverified", "src/main/java/app/Hook.java", "class Hook {\n    boolean ok(HttpServletRequest r, byte[] body) throws Exception {\n"
                                                          "        String ts = r.getHeader(\"X-Hook-Timestamp\");\n        Mac mac = Mac.getInstance(\"HmacSHA256\");\n"
                                                          "        mac.init(key);\n        mac.update((ts + \".\").getBytes());\n        return verify(mac.doFinal(body), r);\n    }\n}\n",
     "class Hook {\n    boolean ok(HttpServletRequest r, byte[] body) throws Exception {\n        String ts = r.getHeader(\"X-Hook-Timestamp\");\n"
     "        if (Duration.between(Instant.ofEpochSecond(Long.parseLong(ts)), Instant.now()).abs().toMinutes() > 5) return false;\n"
     "        Mac mac = Mac.getInstance(\"HmacSHA256\");\n        mac.init(key);\n        mac.update((ts + \".\").getBytes());\n        return verify(mac.doFinal(body), r);\n    }\n}\n"),
    # Java: randomness
    ("insecure-random", "src/main/java/app/Invites.java", "class Invites {\n    private final Random rng = new Random();\n\n    String issue() {\n"
                                                          "        String inviteCode = Long.toHexString(rng.nextLong());\n        return inviteCode;\n    }\n}\n",
     "class Invites {\n    private final SecureRandom rng = new SecureRandom();\n\n    String issue() {\n"
     "        String inviteCode = Long.toHexString(rng.nextLong());\n        return inviteCode;\n    }\n}\n"),
    # Java: data
    ("multi-write-no-transaction", "src/main/java/app/Checkout.java",
     "@Service\nclass Checkout {\n    private final OrderRepository orders;\n    private final StockRepository stock;\n\n"
     "    public void place(Order o, Stock s) {\n        stock.save(s.minus(o.qty()));\n        orders.save(o);\n    }\n}\n",
     "@Service\nclass Checkout {\n    private final OrderRepository orders;\n    private final StockRepository stock;\n\n"
     "    @Transactional\n    public void place(Order o, Stock s) {\n        stock.save(s.minus(o.qty()));\n        orders.save(o);\n    }\n}\n"),
    ("lost-update", "src/main/java/app/WalletService.java", _ACCOUNTS.replace("{finder}", "findById"), _ACCOUNTS.replace("{finder}", "findByIdForUpdate")),
    ("check-then-insert", "src/main/java/app/Signup.java", "@Service\nclass Signup {\n    @Transactional\n    public User join(String email) {\n"
                                                           "        if (users.existsByEmail(email)) throw new Taken(email);\n        return users.save(new User(email));\n    }\n}\n",
     "@Service\nclass Signup {\n    @Transactional\n    public User join(String email) {\n        try {\n            return users.saveAndFlush(new User(email));\n"
     "        } catch (DataIntegrityViolationException e) {\n            throw new Taken(email);\n        }\n    }\n}\n"),
    ("retry-not-idempotent", "src/main/java/app/Payouts.java", "@Service\nclass Payouts {\n    private final BankClient bank;\n\n    @Retryable(maxAttempts = 3)\n"
                                                               "    public Receipt pay(Payout p) {\n        return bank.transferFunds(p);\n    }\n}\n",
     "@Service\nclass Payouts {\n    private final BankClient bank;\n\n    @Retryable(maxAttempts = 3)\n    public Balance balance(String account) {\n"
     "        return bank.fetchBalance(account);\n    }\n}\n"),
    ("checkpoint-before-effect", "src/main/java/app/Listener.java", "@Component\nclass Listener {\n    @KafkaListener(topics = \"orders\")\n"
                                                                    "    public void on(ConsumerRecord<String, String> r, Acknowledgment ack) {\n        ack.acknowledge();\n"
                                                                    "        pool.submit(() -> fulfilment.handle(r.value()));\n    }\n}\n",
     "@Component\nclass Listener {\n    @KafkaListener(topics = \"orders\")\n    public void on(ConsumerRecord<String, String> r, Acknowledgment ack) {\n"
     "        fulfilment.handle(r.value());\n        ack.acknowledge();\n    }\n}\n"),
    ("lock-without-fencing", "src/main/java/app/Nightly.java", "class Nightly {\n    void run(RedissonClient redisson) {\n        RLock lock = redisson.getLock(\"nightly\");\n"
                                                               "        lock.lock(30, TimeUnit.SECONDS);\n        try { export(); } finally { lock.unlock(); }\n    }\n}\n",
     "class Nightly {\n    void run(RedissonClient redisson) {\n        RLock lock = redisson.getLock(\"nightly\");\n"
     "        lock.lock();\n        try { export(); } finally { lock.unlock(); }\n    }\n}\n"),
    ("nonatomic-state-write", "src/main/java/app/State.java", "class State {\n    void save(byte[] b) throws IOException {\n"
                                                              "        Files.write(path, b, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);\n    }\n}\n",
     "class State {\n    void save(byte[] b) throws IOException {\n        Path tmp = Files.createTempFile(path.getParent(), \"state\", \".tmp\");\n"
     "        Files.write(tmp, b, StandardOpenOption.TRUNCATE_EXISTING);\n        Files.move(tmp, path, StandardCopyOption.ATOMIC_MOVE);\n    }\n}\n"),
    ("unsynchronized-state", "src/main/java/app/RateTable.java", "@Component\nclass RateTable {\n    private final Map<String, Integer> hits = new HashMap<>();\n\n"
                                                                 "    public void seen(String ip) {\n        hits.merge(ip, 1, Integer::sum);\n    }\n}\n",
     "@Component\nclass RateTable {\n    private final Map<String, Integer> hits = new ConcurrentHashMap<>();\n\n"
     "    public void seen(String ip) {\n        hits.merge(ip, 1, Integer::sum);\n    }\n}\n"),
    ("assert-validation", "src/main/java/app/Withdrawals.java", "@Service\nclass Withdrawals {\n    public void take(Account a, BigDecimal amount) {\n"
                                                                "        assert amount.signum() > 0 : \"positive\";\n        a.debit(amount);\n    }\n}\n",
     "@Service\nclass Withdrawals {\n    public void take(Account a, BigDecimal amount) {\n"
     "        if (amount.signum() <= 0) throw new IllegalArgumentException(\"positive\");\n        a.debit(amount);\n    }\n}\n"),
]

# Regressions from the third fresh review: safe forms that once blocked gate or were reported, each the near miss of the unsafe form beside it.
_FILTER = ("func (s *Store) Search(ctx context.Context, f Filter) (*sql.Rows, error) {\n\tconds := []string{\"1=1\"}\n\targs := []interface{}{}\n"
           "\tif f.Name != \"\" {\n\t\tconds = append(conds, {cond})\n\t\targs = append(args, f.Name)\n\t}\n"
           "\tif !f.IncludeDeleted {\n\t\tconds = append(conds, \"deleted_at IS NULL\")\n\t}\n"
           "\tquery := \"SELECT id, name FROM users WHERE \" + strings.Join(conds, \" AND \")\n\treturn s.db.QueryContext(ctx, query, args...)\n}\n")
_SORTED = ("var sortable = map[string]bool{\"name\": true, \"created_at\": true}\n\nfunc (s *Store) List(ctx context.Context, sort string) (*sql.Rows, error) {\n"
           "{check}\tquery := \"SELECT id, name FROM users ORDER BY \" + sort\n\treturn s.db.QueryContext(ctx, query)\n}\n")
_ENFORCE = ("func RequirePermission(enforcer Enforcer, perm string) gin.HandlerFunc {\n\treturn func(c *gin.Context) {\n"
            "\t\tallowed, err := enforcer.Enforce(c.GetString(\"user\"), c.Request.URL.Path, perm)\n"
            "\t\tif err != nil {\n\t\t\tlog.Printf(\"enforce failed: %v\", err)\n{tail}\t\t}\n"
            "{recheck}\t\tc.Next()\n\t}\n}\n")
_ORDER_EVENT = ("func (h *Handler) Touch(c *gin.Context) {\n\tvar order Order\n\tif err := h.db.First(&order, c.Param(\"id\")).Error; err != nil {\n"
                "\t\tif errors.Is(err, gorm.ErrRecordNotFound) {\n\t\t\t{created}\n\t\t\treturn\n\t\t}\n\t\tc.AbortWithStatus(http.StatusForbidden)\n\t\treturn\n\t}\n"
                "\th.db.Create(&OrderEvent{OrderID: order.ID, Kind: \"touched\"})\n}\n")
_CONDITIONS = ("@Repository\npublic class Repo {\n    private final JdbcTemplate jdbc;\n\n    public List<User> search(String name, String status) {\n"
               "        List<String> conditions = new ArrayList<>();\n        List<Object> params = new ArrayList<>();\n"
               "        if (name != null) { conditions.add({cond}); params.add(name); }\n"
               "        if (status != null) { conditions.add(\"status = ?\"); params.add(status); }\n        String sql = \"SELECT id, name FROM users\";\n"
               "        if (!conditions.isEmpty()) {\n            sql += \" WHERE \" + String.join(\" AND \", conditions);\n        }\n"
               "        return jdbc.query(sql, MAPPER, params.toArray());\n    }\n}\n")
_POSTS = ("@RestController\n@RequestMapping(\"/api/posts\")\npublic class PostController {\n    @GetMapping\n    public List<Post> list() { return posts.findAll(); }\n\n"
          "    @GetMapping(\"/{id}\")\n    public Post get(@PathVariable Long id) { return posts.find(id); }\n\n"
          "    @PostMapping\n    @PreAuthorize(\"isAuthenticated()\")\n    public Post create(@RequestBody PostDto dto) { return posts.create(dto); }\n\n"
          "    @PutMapping(\"/{id}\")\n    @PreAuthorize(\"@postSecurity.isOwner(#id)\")\n    public Post update(@PathVariable Long id, @RequestBody PostDto dto) { return posts.update(id, dto); }\n\n"
          "    @DeleteMapping(\"/{id}\")\n{guard}    public void delete(@PathVariable Long id) { posts.delete(id); }\n}\n")

JVMGO_CASES += [
    ("sql-injection", "store/filter.go", _go(_FILTER.replace("{cond}", "\"name = '\" + f.Name + \"'\"")), _go(_FILTER.replace("{cond}", "\"name = ?\""))),
    ("sql-injection", "store/users.go", _go("func (s *Store) ByNames(ctx context.Context, names []string) (*sql.Rows, error) {\n\tquoted := []string{}\n"
                                            "\tfor _, n := range names {\n\t\tquoted = append(quoted, \"'\"+n+\"'\")\n\t}\n"
                                            "\tquery := \"SELECT id FROM users WHERE name IN (\" + strings.Join(quoted, \",\") + \")\"\n\treturn s.db.QueryContext(ctx, query)\n}\n"),
     _go("func (s *Store) ByIDs(ctx context.Context, ids []int64) (*sql.Rows, error) {\n"
         "\tquery := \"SELECT id, name FROM users WHERE id IN (\" + strings.Repeat(\"?,\", len(ids)-1) + \"?)\"\n\targs := make([]interface{}, len(ids))\n"
         "\tfor i, id := range ids {\n\t\targs[i] = id\n\t}\n\treturn s.db.QueryContext(ctx, query, args...)\n}\n")),
    ("sql-injection", "store/sorted.go", _go(_SORTED.replace("{check}", "")), _go(_SORTED.replace("{check}", "\tif !sortable[sort] {\n\t\tsort = \"created_at\"\n\t}\n"))),
    ("fail-open", "middleware/authz.go", _go(_ENFORCE.replace("{tail}", "").replace("\t\t}\n{recheck}", "\t\t} else if !allowed {\n\t\t\tc.AbortWithStatus(http.StatusForbidden)\n"
                                                                                                   "\t\t\treturn\n\t\t}\n"), "package middleware\n\n"),
     _go(_ENFORCE.replace("{tail}", "\t\t\tallowed = false\n").replace("{recheck}", "\t\tif !allowed {\n\t\t\tc.AbortWithStatus(http.StatusForbidden)\n\t\t\treturn\n\t\t}\n"),
         "package middleware\n\n")),
    ("insecure-random", "ws/hub.go", "package ws\n\nimport \"math/rand\"\n\nfunc Serve() string {\n\tresetCode := strconv.Itoa(rand.Intn(1000000))\n\treturn resetCode\n}\n",
     "package ws\n\nimport \"math/rand\"\n\nfunc Serve() {\n\tpingInterval := time.Duration(rand.Int63n(3)) * time.Second\n\tsleeping := time.Duration(rand.Intn(100))\n"
     "\t_, _ = pingInterval, sleeping\n}\n"),
    ("check-then-insert", "handlers/orders.go", _go(_ORDER_EVENT.replace("{created}", "h.db.Create(&order)")),
     _go(_ORDER_EVENT.replace("{created}", "c.JSON(http.StatusNotFound, gin.H{\"error\": \"not found\"})"))),
    ("sql-injection", "src/main/java/app/OrderRepository.java",
     "@Repository\npublic class OrderRepository {\n    public List<Order> findByIds(List<Long> ids) {\n"
     "        StringBuilder sql = new StringBuilder(\"SELECT id, total FROM orders WHERE id IN (\");\n"
     "        sql.append(ids.stream().map(String::valueOf).collect(Collectors.joining(\",\"))).append(\")\");\n        return jdbcTemplate.query(sql.toString(), MAPPER);\n    }\n}\n",
     "@Repository\npublic class OrderRepository {\n    public List<Order> findByIds(List<Long> ids) {\n"
     "        StringBuilder sql = new StringBuilder(\"SELECT id, total FROM orders WHERE id IN (\");\n"
     "        sql.append(String.join(\",\", Collections.nCopies(ids.size(), \"?\"))).append(\")\");\n        return jdbcTemplate.query(sql.toString(), MAPPER, ids.toArray());\n    }\n\n"
     "    public List<Order> findByStatuses(List<String> statuses) {\n"
     "        String sql = \"SELECT id, total FROM orders WHERE status IN (\" + statuses.stream().map(s -> \"?\").collect(Collectors.joining(\",\")) + \")\";\n"
     "        return jdbcTemplate.query(sql, MAPPER, statuses.toArray());\n    }\n}\n"),
    ("sql-injection", "src/main/java/a/Repo.java", _CONDITIONS.replace("{cond}", "\"name = '\" + name + \"'\""), _CONDITIONS.replace("{cond}", "\"name = ?\"")),
    ("fail-open", "src/main/java/app/TokenValidator.java",
     "@Component\npublic class ProjectGate {\n    public boolean isAllowed(String user, String project) {\n        try {\n            return members.check(user, project);\n"
     "        } catch (TimeoutException e) {\n            return true;\n        }\n    }\n}\n",
     "@Component\npublic class TokenValidator {\n    public boolean verifyNotRevoked(String jti) {\n        try {\n            revocations.get(jti);\n            return false;\n"
     "        } catch (NotFoundException e) {\n            return true;\n        }\n    }\n}\n"),
    ("missing-auth", "src/main/java/app/PostController.java", _POSTS.replace("{guard}", ""), _POSTS.replace("{guard}", "    @PreAuthorize(\"hasRole('ADMIN')\")\n")),
    ("insecure-random", "src/main/java/app/HeartbeatService.java",
     "@Service\npublic class Codes {\n    private final Random random = new Random();\n\n    public String next() {\n"
     "        String resetCode = String.valueOf(random.nextInt(1000000));\n        return resetCode;\n    }\n}\n",
     "@Service\npublic class HeartbeatService {\n    private final Random random = new Random();\n\n    public long nextPing() {\n"
     "        long pingDelay = 1000 + random.nextInt(500);\n        int spinWait = ThreadLocalRandom.current().nextInt(10, 50);\n        return pingDelay + spinWait;\n    }\n}\n"),
]
