package drift.junit4;
import java.io.*;
import java.lang.annotation.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import org.junit.runner.*;
import org.junit.runner.notification.*;
public final class DriftJUnit4 {
  private DriftJUnit4() {}
  public interface Replayer { Map<String, Object> execute(Map<String, Object> whenWitness) throws Exception; }
  private static final Set<String> CAPABILITIES = Collections.unmodifiableSet(new HashSet<String>(Arrays.asList(new String[] {
    "allowed_keys", "case_frames", "counterexample_replay", "forbid_keys",
    "inventory_sidecar", "junit4_runner", "not_in", "predicates", "projections", "relational_bounds"
  })));
  public static Map<String, Object> bridgeCapabilities() {
    List<String> caps = new ArrayList<String>(CAPABILITIES); Collections.sort(caps);
    Map<String, Object> out = new LinkedHashMap<String, Object>();
    out.put("bridge", "drift-junit4-legacy"); out.put("capabilities", caps);
    out.put("runtime_baseline", "java-8-legacy"); out.put("schema", "drift.bridge-capabilities/1"); out.put("version", "0.5.0");
    return out;
  }
  public static void requireCapabilities(Collection<String> required) {
    if (required == null) throw new IllegalStateException("bridge.capability_unsupported:null");
    for (Iterator<String> it = required.iterator(); it.hasNext(); ) {
      String cap = it.next(), k = cap == null ? "" : cap.trim();
      if (k.length() == 0 || !CAPABILITIES.contains(k)) throw new IllegalStateException("bridge.capability_unsupported:" + k);
    }
  }
  public static int replayCounterexamples(
      String contractId, String caseId, File cexDirOrFile, Replayer replayer,
      Map<String, Map<String, Object>> frames) throws Exception {
    if (cexDirOrFile == null || !cexDirOrFile.exists()) return 0;
    List<File> files = new ArrayList<File>();
    if (cexDirOrFile.isDirectory()) {
      File[] ch = cexDirOrFile.listFiles();
      if (ch != null) {
        for (int i = 0; i < ch.length; i++) if (ch[i].isFile() && ch[i].getName().endsWith(".cex.json")) files.add(ch[i]);
        Collections.sort(files);
      }
    } else if (cexDirOrFile.getName().endsWith(".cex.json")) files.add(cexDirOrFile);
    int replayed = 0;
    for (int i = 0; i < files.size(); i++) {
      File f = files.get(i);
      Map<String, Object> doc = asMap(new MiniJson(readUtf8(f)).parse());
      if (doc == null || !contractId.equals(doc.get("contract"))) continue;
      Object tc = doc.get("case");
      if (tc instanceof String && ((String) tc).length() > 0 && !caseId.equals(tc)) continue;
      Map<String, Object> wit = asMap(doc.get("witness")), whenIn = wit != null ? asMap(wit.get("when")) : null;
      if (whenIn == null) throw new IllegalStateException("DRIFT: missing witness.when in " + f);
      verify(contractId, caseId, replayer.execute(whenIn), frames);
      replayed++;
    }
    return replayed;
  }
  @Retention(RetentionPolicy.RUNTIME) @Target(ElementType.METHOD)
  public @interface Case { String contract(); String[] value(); String level() default "unit"; }
  private static final InheritableThreadLocal<Set<String>> VERIFIED_CASES = new InheritableThreadLocal<Set<String>>();
  private static final Map<String, Map<String, Object>> VIEW_CACHE = new HashMap<String, Map<String, Object>>();
  public static void clearCache() { synchronized (VIEW_CACHE) { VIEW_CACHE.clear(); } }
  private static Set<String> currentVerifiedSet() {
    Set<String> s = VERIFIED_CASES.get();
    if (s == null) { s = new HashSet<String>(); VERIFIED_CASES.set(s); }
    return s;
  }
  public static void verify(String contractId, String caseId, Map<String, Object> observations) { verify(contractId, caseId, observations, null); }
  @SuppressWarnings("unchecked")
  public static void verify(
      String contractId, String caseId, Map<String, Object> observations,
      Map<String, Map<String, Object>> frames) {
    if (observations == null) throw new AssertionError("DRIFT: null observations for " + contractId + "." + caseId);
    Map<String, Object> view = loadResolvedView(contractId), cases = asMap(view.get("cases"));
    if (cases == null || !cases.containsKey(caseId)) throw new AssertionError("DRIFT: unknown case " + contractId + "." + caseId);
    Map<String, Object> caseMap = asMap(cases.get(caseId));
    if (caseMap.containsKey("status")) throw new AssertionError("DRIFT: exempt case " + contractId + "." + caseId);
    Map<String, Object> thenMap = asMap(caseMap.get("then")), projRoot = asMap(view.get("projections")), projThen = projRoot != null ? asMap(projRoot.get("then")) : null;
    if (thenMap != null) for (Iterator<Map.Entry<String, Object>> it = thenMap.entrySet().iterator(); it.hasNext(); ) {
      Map.Entry<String, Object> e = it.next();
      checkThenPredicate(contractId, caseId, e.getKey(), e.getValue(), observations, projThen);
    }
    Map<String, Object> scopeMap = asMap(view.get("scope"));
    List<Object> scopeWrites = scopeMap != null ? asList(scopeMap.get("writes")) : null;
    List<Object> caseWrites = caseMap.containsKey("writes") ? asList(caseMap.get("writes")) : null;
    List<Object> rawAllowed = caseWrites != null ? caseWrites : (scopeWrites != null ? scopeWrites : Collections.emptyList());
    Set<String> allowedWrites = new HashSet<String>(), allowedBases = new HashSet<String>(), checkedReq = new HashSet<String>();
    for (int i = 0; i < rawAllowed.size(); i++) {
      String w = String.valueOf(rawAllowed.get(i)); int h = w.indexOf('#');
      allowedWrites.add(w); allowedBases.add(h >= 0 ? w.substring(0, h) : w);
    }
    boolean allFramesObserved = true;
    if (scopeWrites != null && caseWrites != null) for (int i = 0; i < scopeWrites.size(); i++) {
      String res = String.valueOf(scopeWrites.get(i)); int h = res.indexOf('#'); String baseRes = h >= 0 ? res.substring(0, h) : res;
      if (allowedWrites.contains(res) || allowedWrites.contains(baseRes) || (h < 0 && allowedBases.contains(res))) continue;
      checkedReq.add(res); checkedReq.add(baseRes);
      Map<String, Object> fObs = frames != null ? (frames.containsKey(res) ? frames.get(res) : frames.get(baseRes)) : null;
      if (fObs == null || !checkSingleFrame(fObs, contractId + "." + caseId + " " + res, false)) allFramesObserved = false;
    }
    if (frames != null) for (Iterator<Map.Entry<String, Map<String, Object>>> fit = frames.entrySet().iterator(); fit.hasNext(); ) {
      Map.Entry<String, Map<String, Object>> fe = fit.next(); String k = fe.getKey(); int h = k.indexOf('#'); String baseK = h >= 0 ? k.substring(0, h) : k;
      if (checkedReq.contains(k) || allowedWrites.contains(k) || allowedWrites.contains(baseK) || (h < 0 && allowedBases.contains(k))) continue;
      if (fe.getValue() != null) checkSingleFrame(fe.getValue(), contractId + "." + caseId + " " + k, true);
    }
    if (allFramesObserved) currentVerifiedSet().add(contractId + ":" + caseId);
  }
  private static boolean checkSingleFrame(Map<String, Object> fObs, String target, boolean ambient) {
    boolean chk = false;
    if (fObs.containsKey("writes")) { chk = true; if (toNonNegLong(fObs.get("writes")) != 0L) throw new AssertionError((ambient ? "DRIFT undeclared write on perimeter resource " : "DRIFT frame violation on ") + target); }
    if (fObs.containsKey("before") && fObs.containsKey("after")) { chk = true; if (!valuesEqual(fObs.get("before"), fObs.get("after"))) throw new AssertionError((ambient ? "DRIFT undeclared state mutation on perimeter resource " : "DRIFT frame snapshot mutation on ") + target); }
    if (Boolean.FALSE.equals(fObs.get("observed"))) return false;
    return chk;
  }
  private static boolean hasKeyRecursive(Object val, String fk, boolean isRoot) {
    if (val instanceof List) {
      List<?> l = (List<?>) val;
      for (int i = 0; i < l.size(); i++) if (hasKeyRecursive(l.get(i), fk, false)) return true;
      return false;
    }
    if (!(val instanceof Map)) return false;
    for (Iterator<?> it = ((Map<?, ?>) val).entrySet().iterator(); it.hasNext(); ) {
      Map.Entry<?, ?> e = (Map.Entry<?, ?>) it.next();
      String k = String.valueOf(e.getKey());
      if (fk.equals(k)) return true;
      if (isRoot && "_frame".equals(k) && !"_frame".equals(fk) && e.getValue() instanceof Map) continue;
      if (hasKeyRecursive(e.getValue(), fk, false)) return true;
    }
    return false;
  }
  @SuppressWarnings("unchecked")
  private static void checkThenPredicate(
      String contractId, String caseId, String key, Object expected,
      Map<String, Object> observations, Map<String, Object> projThen) {
    if (expected instanceof Map) {
      Map<String, Object> rel = (Map<String, Object>) expected;
      List<Object> forbidden = asList(rel.get("forbid_keys")), allowed = asList(rel.get("allowed_keys"));
      Object fkT = observations.containsKey(key) && observations.get(key) instanceof Map ? observations.get(key) : observations;
      if (forbidden != null) {
        for (int i = 0; i < forbidden.size(); i++) {
          String fk = String.valueOf(forbidden.get(i));
          if (hasKeyRecursive(fkT, fk, fkT == observations)) throw new AssertionError("DRIFT forbid_keys violation: " + fk);
        }
      } else if (rel.get("forbid_keys") instanceof String && !hasKeyRecursive(fkT, (String) rel.get("forbid_keys"), fkT == observations)) {
        throw new AssertionError("DRIFT drop-forbid-key mutant killed on " + key);
      }
      if (allowed != null) {
        Set<String> allowSet = new HashSet<String>();
        for (int i = 0; i < allowed.size(); i++) allowSet.add(String.valueOf(allowed.get(i)));
        for (Iterator<String> kit = observations.keySet().iterator(); kit.hasNext(); ) {
          String ok = kit.next();
          if ("_frame".equals(ok) && observations.get(ok) instanceof Map) continue;
          if (!allowSet.contains(ok)) throw new AssertionError("DRIFT allowed_keys violation: " + ok);
        }
      }
    }
    Object actual = extractObservedValue(key, observations, projThen, contractId, caseId, expected);
    if (expected instanceof Map && isRelationalTable((Map<String, Object>) expected)) {
      checkRelationalBounds(contractId, caseId, key, (Map<String, Object>) expected, actual);
      return;
    }
    if (!valuesEqual(expected, actual)) throw new AssertionError("DRIFT mismatch on " + contractId + "." + caseId + "." + key);
  }
  private static boolean isRelationalTable(Map<String, Object> m) {
    if (m == null || m.isEmpty()) return false;
    Set<String> known = new HashSet<String>(Arrays.asList(new String[] {
      "min", "max", "in", "not_in", "len", "min_len", "max_len", "non_empty",
      "prefix", "suffix", "contains", "allowed_keys", "forbid_keys",
      "monotonic", "step_max_delta", "sum_total", "approx", "abs_tol", "rel_tol", "balance_fields", "unit", "unit_conversion"
    }));
    for (Iterator<String> it = m.keySet().iterator(); it.hasNext(); ) if (!known.contains(String.valueOf(it.next()))) return false;
    return true;
  }
  private static void checkRelationalBounds(
      String contractId, String caseId, String key, Map<String, Object> rel, Object actual) {
    String loc = contractId + "." + caseId + "." + key;
    if (rel.containsKey("approx")) {
      double ap = toDouble(rel.get("approx"));
      double at = rel.containsKey("abs_tol") ? toDouble(rel.get("abs_tol")) : 0.0;
      double rt = rel.containsKey("rel_tol") ? toDouble(rel.get("rel_tol")) : 0.0;
      if (Math.abs(toDouble(actual) - ap) > at + rt * Math.abs(ap)) throw new AssertionError("DRIFT approx violation on " + loc);
    }
    if (rel.containsKey("min") && toDouble(actual) + 1e-9 < toDouble(rel.get("min"))) throw new AssertionError("DRIFT min violation on " + loc);
    if (rel.containsKey("max") && toDouble(actual) - 1e-9 > toDouble(rel.get("max"))) throw new AssertionError("DRIFT max violation on " + loc);
    if (rel.containsKey("in")) {
      List<Object> dom = asList(rel.get("in")); boolean hit = false;
      if (dom != null) for (int i = 0; i < dom.size(); i++) if (valuesEqual(dom.get(i), actual)) { hit = true; break; }
      if (!hit) throw new AssertionError("DRIFT in violation on " + loc);
    }
    if (rel.containsKey("not_in")) {
      if (actual == null) throw new AssertionError("DRIFT not_in null violation on " + loc);
      List<Object> ex = asList(rel.get("not_in"));
      if (ex != null) for (int i = 0; i < ex.size(); i++) if (valuesEqual(ex.get(i), actual)) throw new AssertionError("DRIFT not_in violation on " + loc);
    }
    if (rel.containsKey("len") && valueLength(actual) != toNonNegLong(rel.get("len"))) throw new AssertionError("DRIFT len violation on " + loc);
    if (rel.containsKey("min_len") && valueLength(actual) < toNonNegLong(rel.get("min_len"))) throw new AssertionError("DRIFT min_len violation on " + loc);
    if (rel.containsKey("max_len") && valueLength(actual) > toNonNegLong(rel.get("max_len"))) throw new AssertionError("DRIFT max_len violation on " + loc);
    if (rel.containsKey("non_empty") && (Boolean.TRUE.equals(rel.get("non_empty")) ? valueLength(actual) <= 0L : valueLength(actual) != 0L)) throw new AssertionError("DRIFT non_empty violation on " + loc);
    if (rel.containsKey("prefix") && (!(actual instanceof String) || !((String) actual).startsWith(String.valueOf(rel.get("prefix"))))) throw new AssertionError("DRIFT prefix violation on " + loc);
    if (rel.containsKey("suffix") && (!(actual instanceof String) || !((String) actual).endsWith(String.valueOf(rel.get("suffix"))))) throw new AssertionError("DRIFT suffix violation on " + loc);
    if (rel.containsKey("contains")) {
      Object cExp = rel.get("contains");
      if (actual instanceof String) {
        if (!(cExp instanceof String) || ((String) actual).indexOf((String) cExp) < 0) throw new AssertionError("DRIFT contains violation on " + loc);
      } else if (actual instanceof List) {
        List<?> al = (List<?>) actual, rl = cExp instanceof List ? (List<?>) cExp : Collections.singletonList(cExp);
        for (int i = 0; i < rl.size(); i++) {
          boolean hit = false;
          for (int j = 0; j < al.size(); j++) if (valuesEqual(al.get(j), rl.get(i))) { hit = true; break; }
          if (!hit) throw new AssertionError("DRIFT contains violation on " + loc);
        }
      } else throw new AssertionError("DRIFT contains violation on " + loc);
    }
  }
  private static Object extractObservedValue(
      String key, Map<String, Object> observations, Map<String, Object> projThen,
      String contractId, String caseId, Object expected) {
    if (observations.containsKey(key)) return observations.get(key);
    if (projThen != null && projThen.containsKey(key)) {
      String raw = String.valueOf(projThen.get(key)); int col = raw.indexOf(":/");
      String ptr = col >= 0 ? raw.substring(col + 1) : raw;
      if (ptr.startsWith("/") && observations.containsKey(ptr.substring(1))) return observations.get(ptr.substring(1));
    }
    if (expected instanceof Map) {
      Map<String, Object> rel = asMap(expected);
      if (rel != null && (rel.containsKey("forbid_keys") || rel.containsKey("allowed_keys")) && rel.size() == 1) return observations;
    }
    throw new AssertionError("DRIFT missing observation for " + contractId + "." + caseId + "." + key);
  }
  public static final class Listener extends RunListener {
    private final File eventsFile;
    private final Set<String> classes = Collections.synchronizedSet(new HashSet<String>());
    private final Set<String> tests = Collections.synchronizedSet(new HashSet<String>());
    private final List<String> eventLines = Collections.synchronizedList(new ArrayList<String>());
    private final Map<String, String> outcomesByTest = new ConcurrentHashMap<String, String>();
    public Listener(File eventsFile) { this.eventsFile = eventsFile; }
    public Listener() {
      String p = System.getProperty("drift.events");
      if (p == null || p.trim().length() == 0) p = System.getenv("DRIFT_EVENTS");
      this.eventsFile = p != null && p.trim().length() > 0 ? new File(p.trim()) : null;
    }
    private static String keyOf(Description d) { return d == null ? "" : (d.getClassName() + "#" + d.getMethodName()); }
    private void recordDesc(Description d) {
      if (d != null && d.getClassName() != null && d.getMethodName() != null) { classes.add(d.getClassName()); tests.add(keyOf(d)); }
    }
    @Override public void testRunStarted(Description d) { collectInventory(d); }
    private void collectInventory(Description d) {
      if (d == null) return;
      if (d.isTest()) recordDesc(d);
      ArrayList<Description> ch = d.getChildren();
      if (ch != null) for (int i = 0; i < ch.size(); i++) collectInventory(ch.get(i));
    }
    @Override public void testStarted(Description d) {
      outcomesByTest.put(keyOf(d), "passed"); currentVerifiedSet().clear(); recordDesc(d);
    }
    @Override public void testFailure(Failure f) { outcomesByTest.put(keyOf(f.getDescription()), "failed"); }
    @Override public void testAssumptionFailure(Failure f) {
      String k = keyOf(f.getDescription());
      if (!"failed".equals(outcomesByTest.get(k))) outcomesByTest.put(k, "skipped");
    }
    @Override public void testIgnored(Description d) {
      recordDesc(d); emitEventForDescription(d, "disabled", Collections.<String>emptySet());
    }
    @Override public void testFinished(Description d) {
      Set<String> v = new HashSet<String>(currentVerifiedSet()); currentVerifiedSet().clear();
      String out = outcomesByTest.remove(keyOf(d));
      emitEventForDescription(d, out != null ? out : "passed", v);
    }
    private void emitEventForDescription(Description d, String outcome, Set<String> verified) {
      Case ann = findCaseAnnotation(d);
      if (ann == null || ann.value() == null || ann.value().length == 0) return;
      String cid = ann.contract(), dig = String.valueOf(loadResolvedView(cid).get("digest")), tid = keyOf(d);
      String[] raw = ann.value();
      List<String> cl = new ArrayList<String>(), rl = new ArrayList<String>();
      for (int i = 0; i < raw.length; i++) {
        String c = raw[i]; cl.add(c);
        if ("passed".equals(outcome) && verified.contains(cid + ":" + c)) rl.add(c);
      }
      StringBuilder sb = new StringBuilder(256);
      sb.append("{\"cases\":"); appendStringArray(sb, cl);
      sb.append(",\"contract\":\"").append(escapeJson(cid)).append("\",\"digest\":\"").append(escapeJson(dig)).append("\",\"level\":\"").append(escapeJson(ann.level())).append("\",\"outcome\":\"").append(escapeJson(outcome)).append("\"");
      if (!rl.isEmpty()) { sb.append(",\"read\":"); appendStringArray(sb, rl); }
      sb.append(",\"test\":\"").append(escapeJson(tid)).append("\"}");
      eventLines.add(sb.toString());
    }
    private Case findCaseAnnotation(Description d) {
      Case direct = d.getAnnotation(Case.class);
      if (direct != null) return direct;
      try { return Class.forName(d.getClassName()).getDeclaredMethod(d.getMethodName()).getAnnotation(Case.class); }
      catch (Exception e) { return null; }
    }
    @Override
    public void testRunFinished(Result result) throws Exception {
      if (eventsFile == null) return;
      File p = eventsFile.getParentFile();
      if (p != null && !p.exists()) p.mkdirs();
      StringBuilder ev = new StringBuilder();
      for (int i = 0; i < eventLines.size(); i++) ev.append(eventLines.get(i)).append('\n');
      writeUtf8Atomic(eventsFile, ev.toString());
      List<String> sc = new ArrayList<String>(classes), st = new ArrayList<String>(tests);
      Collections.sort(sc); Collections.sort(st);
      StringBuilder meta = new StringBuilder(256);
      meta.append("{\n  \"classes\": "); appendStringArray(meta, sc);
      meta.append(",\n  \"tests\": "); appendStringArray(meta, st);
      meta.append(",\n  \"version\": 1\n}\n");
      String n = eventsFile.getName(), b = n.endsWith(".jsonl") ? n.substring(0, n.length() - 6) : n;
      writeUtf8Atomic(new File(p, b + ".meta.json"), meta.toString());
    }
  }
  private static void writeUtf8Atomic(File target, String content) throws IOException {
    File tmp = new File(target.getParentFile(), target.getName() + ".tmp");
    OutputStreamWriter w = new OutputStreamWriter(new FileOutputStream(tmp), "UTF-8");
    try { w.write(content); } finally { w.close(); }
    if (target.exists()) target.delete();
    if (!tmp.renameTo(target)) {
      OutputStreamWriter d = new OutputStreamWriter(new FileOutputStream(target), "UTF-8");
      try { d.write(content); } finally { d.close(); }
      tmp.delete();
    }
  }
  private static void appendStringArray(StringBuilder sb, List<String> items) {
    sb.append('[');
    for (int i = 0; i < items.size(); i++) { if (i > 0) sb.append(','); sb.append('"').append(escapeJson(items.get(i))).append('"'); }
    sb.append(']');
  }
  private static String escapeJson(String s) {
    StringBuilder sb = new StringBuilder(s.length() + 8);
    for (int i = 0; i < s.length(); i++) {
      char c = s.charAt(i);
      if (c == '"' || c == '\\') sb.append('\\').append(c);
      else if (c == '\n') sb.append("\\n"); else if (c == '\r') sb.append("\\r"); else if (c == '\t') sb.append("\\t");
      else if (c < 0x20) { String h = Integer.toHexString(c); sb.append("\\u00").append(h.length() == 1 ? "0" + h : h); }
      else sb.append(c);
    }
    return sb.toString();
  }
  private static Map<String, Object> loadResolvedView(String contractId) {
    synchronized (VIEW_CACHE) {
      if (VIEW_CACHE.containsKey(contractId)) return VIEW_CACHE.get(contractId);
      String dir = System.getProperty("drift.resolved");
      if (dir == null || dir.trim().length() == 0) dir = System.getenv("DRIFT_RESOLVED");
      if (dir == null || dir.trim().length() == 0) throw new IllegalStateException("DRIFT: missing drift.resolved / DRIFT_RESOLVED");
      File f = new File(new File(dir.trim()), contractId + ".json");
      Map<String, Object> map = asMap(new MiniJson(readUtf8(f)).parse());
      if (map == null) throw new IllegalStateException("DRIFT: invalid resolved JSON in " + f);
      VIEW_CACHE.put(contractId, map); return map;
    }
  }
  private static String readUtf8(File f) {
    try {
      BufferedReader r = new BufferedReader(new InputStreamReader(new FileInputStream(f), "UTF-8"));
      try { StringBuilder sb = new StringBuilder(); char[] b = new char[2048]; int n; while ((n = r.read(b)) >= 0) sb.append(b, 0, n); return sb.toString(); }
      finally { r.close(); }
    } catch (IOException e) { throw new IllegalStateException("DRIFT: cannot read " + f + ": " + e.getMessage(), e); }
  }
  @SuppressWarnings("unchecked") private static Map<String, Object> asMap(Object o) { return o instanceof Map ? (Map<String, Object>) o : null; }
  @SuppressWarnings("unchecked") private static List<Object> asList(Object o) { return o instanceof List ? (List<Object>) o : null; }
  private static double toDouble(Object o) {
    if (o instanceof Number) { double d = ((Number) o).doubleValue(); if (!Double.isNaN(d) && !Double.isInfinite(d)) return d; }
    throw new AssertionError("DRIFT: expected finite numeric value, got " + o);
  }
  private static long toNonNegLong(Object o) {
    if (o instanceof Number) { double d = ((Number) o).doubleValue(); if (!Double.isNaN(d) && !Double.isInfinite(d) && d >= 0.0 && d == Math.rint(d)) return ((Number) o).longValue(); }
    throw new AssertionError("DRIFT: expected non-negative integer value, got " + o);
  }
  private static long valueLength(Object o) {
    if (o instanceof String) return ((String) o).length();
    if (o instanceof List) return ((List<?>) o).size();
    if (o instanceof Map) return ((Map<?, ?>) o).size();
    throw new AssertionError("DRIFT: value has no length: " + o);
  }
  private static boolean valuesEqual(Object a, Object b) {
    if (a == b) return true;
    if (a == null || b == null) return false;
    if (a instanceof Number && b instanceof Number) {
      if ((a instanceof Long || a instanceof Integer) && (b instanceof Long || b instanceof Integer)) return ((Number) a).longValue() == ((Number) b).longValue();
      return Math.abs(((Number) a).doubleValue() - ((Number) b).doubleValue()) <= 1e-9;
    }
    if (a instanceof List && b instanceof List) {
      List<?> la = (List<?>) a, lb = (List<?>) b;
      if (la.size() != lb.size()) return false;
      for (int i = 0; i < la.size(); i++) if (!valuesEqual(la.get(i), lb.get(i))) return false;
      return true;
    }
    if (a instanceof Map && b instanceof Map) {
      Map<?, ?> ma = (Map<?, ?>) a, mb = (Map<?, ?>) b;
      if (ma.size() != mb.size()) return false;
      for (Iterator<?> it = ma.entrySet().iterator(); it.hasNext(); ) {
        Map.Entry<?, ?> e = (Map.Entry<?, ?>) it.next();
        if (!mb.containsKey(e.getKey()) || !valuesEqual(e.getValue(), mb.get(e.getKey()))) return false;
      }
      return true;
    }
    return a.equals(b);
  }
  private static final class MiniJson {
    private final String s; private int pos;
    MiniJson(String s) { this.s = s; }
    Object parse() { skipWs(); Object v = readValue(); skipWs(); return v; }
    private void skipWs() { while (pos < s.length() && " \t\n\r".indexOf(s.charAt(pos)) >= 0) pos++; }
    private Object readValue() {
      skipWs(); char c = s.charAt(pos);
      if (c == '{') return readObject();
      if (c == '[') return readArray();
      if (c == '"') return readString();
      if (c == 't' && s.startsWith("true", pos)) { pos += 4; return Boolean.TRUE; }
      if (c == 'f' && s.startsWith("false", pos)) { pos += 5; return Boolean.FALSE; }
      if (c == 'n' && s.startsWith("null", pos)) { pos += 4; return null; }
      return readNumber();
    }
    private Map<String, Object> readObject() {
      pos++; Map<String, Object> m = new LinkedHashMap<String, Object>(); skipWs();
      if (s.charAt(pos) == '}') { pos++; return m; }
      for (;;) {
        skipWs(); String k = readString(); skipWs();
        if (s.charAt(pos++) != ':') throw new IllegalStateException("Expected ':'");
        m.put(k, readValue()); skipWs(); char c = s.charAt(pos++);
        if (c == '}') return m;
        if (c != ',') throw new IllegalStateException("Expected ','");
      }
    }
    private List<Object> readArray() {
      pos++; List<Object> l = new ArrayList<Object>(); skipWs();
      if (s.charAt(pos) == ']') { pos++; return l; }
      for (;;) {
        l.add(readValue()); skipWs(); char c = s.charAt(pos++);
        if (c == ']') return l;
        if (c != ',') throw new IllegalStateException("Expected ','");
      }
    }
    private String readString() {
      pos++; StringBuilder sb = new StringBuilder();
      while (pos < s.length()) {
        char c = s.charAt(pos++);
        if (c == '"') return sb.toString();
        if (c == '\\') {
          char e = s.charAt(pos++);
          if (e == '"' || e == '\\' || e == '/') sb.append(e);
          else if (e == 'n') sb.append('\n'); else if (e == 'r') sb.append('\r'); else if (e == 't') sb.append('\t');
          else if (e == 'b') sb.append('\b'); else if (e == 'f') sb.append('\f');
          else if (e == 'u') { sb.append((char) Integer.parseInt(s.substring(pos, pos + 4), 16)); pos += 4; }
        } else sb.append(c);
      }
      throw new IllegalStateException("EOF");
    }
    private Number readNumber() {
      int st = pos; boolean fl = false;
      while (pos < s.length()) {
        char c = s.charAt(pos);
        if ((c >= '0' && c <= '9') || c == '-' || c == '+') pos++;
        else if (c == '.' || c == 'e' || c == 'E') { fl = true; pos++; }
        else break;
      }
      String num = s.substring(st, pos);
      return fl ? (Number) Double.valueOf(num) : (Number) Long.valueOf(num);
    }
  }
}
