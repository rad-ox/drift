package drift.junit4;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import org.junit.runner.Description;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;

/**
* Zero-dependency Java 6 source-compatible JUnit 4 legacy bridge for DRIFT (SPEC sections 30.1, 31.3, D275, D281).
*/
public final class DriftJUnit4 {
  private DriftJUnit4() {}

  public interface Replayer {
    Map<String, Object> execute(Map<String, Object> whenWitness) throws Exception;
  }

  private static final Set<String> CAPABILITIES = createCapabilities();

  private static Set<String> createCapabilities() {
    Set<String> s = new HashSet<String>(Arrays_asList(new String[] {
      "allowed_keys", "case_frames", "counterexample_replay", "forbid_keys",
      "inventory_sidecar", "junit4_runner", "not_in", "predicates", "projections", "relational_bounds"
    }));
    return Collections.unmodifiableSet(s);
  }

  private static List<String> Arrays_asList(String[] items) {
    List<String> out = new ArrayList<String>(items.length);
    for (int i = 0; i < items.length; i++) out.add(items[i]);
    return out;
  }

  public static Map<String, Object> bridgeCapabilities() {
    List<String> caps = new ArrayList<String>(CAPABILITIES);
    Collections.sort(caps);
    Map<String, Object> out = new LinkedHashMap<String, Object>();
    out.put("bridge", "drift-junit4-legacy");
    out.put("capabilities", caps);
    out.put("runtime_baseline", "java-8-legacy");
    out.put("schema", "drift.bridge-capabilities/1");
    out.put("version", "0.3.3");
    return out;
  }

  public static void requireCapabilities(java.util.Collection<String> required) {
    if (required == null) throw new IllegalStateException("bridge.capability_unsupported:null");
    for (Iterator<String> it = required.iterator(); it.hasNext(); ) {
      String cap = it.next();
      String k = cap == null ? "" : cap.trim();
      if (k.length() == 0 || !CAPABILITIES.contains(k)) {
        throw new IllegalStateException("bridge.capability_unsupported:" + k);
      }
    }
  }

  public static int replayCounterexamples(
      String contractId, String caseId, File cexDirOrFile, Replayer replayer,
      Map<String, Map<String, Object>> frames) throws Exception {
    if (cexDirOrFile == null || !cexDirOrFile.exists()) return 0;
    List<File> files = new ArrayList<File>();
    if (cexDirOrFile.isDirectory()) {
      File[] children = cexDirOrFile.listFiles();
      if (children != null) {
        for (int i = 0; i < children.length; i++) {
          if (children[i].isFile() && children[i].getName().endsWith(".cex.json")) files.add(children[i]);
        }
        Collections.sort(files);
      }
    } else if (cexDirOrFile.getName().endsWith(".cex.json")) files.add(cexDirOrFile);
    int replayed = 0;
    for (int i = 0; i < files.size(); i++) {
      File f = files.get(i);
      Map<String, Object> doc = asMap(new MiniJson(readUtf8(f)).parse());
      if (doc == null || !contractId.equals(doc.get("contract"))) continue;
      Object targetCase = doc.get("case");
      if (targetCase instanceof String && ((String) targetCase).length() > 0 && !caseId.equals(targetCase)) continue;
      Map<String, Object> wit = asMap(doc.get("witness"));
      Map<String, Object> whenIn = wit != null ? asMap(wit.get("when")) : null;
      if (whenIn == null) throw new IllegalStateException("DRIFT: missing witness.when in " + f);
      verify(contractId, caseId, replayer.execute(whenIn), frames);
      replayed++;
    }
    return replayed;
  }

  @Retention(RetentionPolicy.RUNTIME)
  @Target(ElementType.METHOD)
  public @interface Case {
    String contract();
    String[] value();
    String level() default "unit";
  }

  private static final InheritableThreadLocal<Set<String>> VERIFIED_CASES = new InheritableThreadLocal<Set<String>>();
  private static final Map<String, Map<String, Object>> VIEW_CACHE = new HashMap<String, Map<String, Object>>();

  public static void clearCache() { synchronized (VIEW_CACHE) { VIEW_CACHE.clear(); } }

  private static Set<String> currentVerifiedSet() {
    Set<String> set = VERIFIED_CASES.get();
    if (set == null) { set = new HashSet<String>(); VERIFIED_CASES.set(set); }
    return set;
  }

  public static void verify(String contractId, String caseId, Map<String, Object> observations) {
    verify(contractId, caseId, observations, null);
  }

  @SuppressWarnings("unchecked")
  public static void verify(
      String contractId, String caseId, Map<String, Object> observations,
      Map<String, Map<String, Object>> frames) {
    if (observations == null) throw new AssertionError("DRIFT: null observations for " + contractId + "." + caseId);
    Map<String, Object> view = loadResolvedView(contractId);
    Map<String, Object> cases = asMap(view.get("cases"));
    if (cases == null || !cases.containsKey(caseId)) throw new AssertionError("DRIFT: unknown case " + contractId + "." + caseId);
    Map<String, Object> caseMap = asMap(cases.get(caseId));
    if (caseMap.containsKey("status")) throw new AssertionError("DRIFT: exempt case " + contractId + "." + caseId);
    Map<String, Object> thenMap = asMap(caseMap.get("then"));
    Map<String, Object> projRoot = asMap(view.get("projections"));
    Map<String, Object> projThen = projRoot != null ? asMap(projRoot.get("then")) : null;
    if (thenMap != null) {
      for (Iterator<Map.Entry<String, Object>> it = thenMap.entrySet().iterator(); it.hasNext(); ) {
        Map.Entry<String, Object> e = it.next();
        checkThenPredicate(contractId, caseId, e.getKey(), e.getValue(), observations, projThen);
      }
    }
    Map<String, Object> scopeMap = asMap(view.get("scope"));
    List<Object> scopeWrites = scopeMap != null ? asList(scopeMap.get("writes")) : null;
    List<Object> caseWrites = caseMap.containsKey("writes") ? asList(caseMap.get("writes")) : null;
    boolean allFramesObserved = true;
    if (scopeWrites != null && caseWrites != null) {
      Set<String> allowedWrites = new HashSet<String>();
      for (int i = 0; i < caseWrites.size(); i++) allowedWrites.add(String.valueOf(caseWrites.get(i)));
      for (int i = 0; i < scopeWrites.size(); i++) {
        String res = String.valueOf(scopeWrites.get(i));
        if (allowedWrites.contains(res)) continue;
        Map<String, Object> frameObs = frames != null ? frames.get(res) : null;
        if (frameObs == null) { allFramesObserved = false; continue; }
        boolean checkedAny = false;
        if (frameObs.containsKey("writes")) {
          checkedAny = true;
          long wCount = toLong(frameObs.get("writes"));
          if (wCount != 0L) throw new AssertionError("DRIFT frame violation on " + contractId + "." + caseId + " " + res);
        }
        if (frameObs.containsKey("before") && frameObs.containsKey("after")) {
          checkedAny = true;
          if (!valuesEqual(frameObs.get("before"), frameObs.get("after"))) {
            throw new AssertionError("DRIFT frame snapshot mutation on " + contractId + "." + caseId + " " + res);
          }
        }
        if (!checkedAny) allFramesObserved = false;
      }
    }
    if (allFramesObserved) currentVerifiedSet().add(contractId + ":" + caseId);
  }

  @SuppressWarnings("unchecked")
  private static void checkThenPredicate(
      String contractId, String caseId, String key, Object expected,
      Map<String, Object> observations, Map<String, Object> projThen) {
    if (expected instanceof Map) {
      Map<String, Object> rel = (Map<String, Object>) expected;
      List<Object> forbidden = asList(rel.get("forbid_keys"));
      if (forbidden != null) {
        for (int i = 0; i < forbidden.size(); i++) {
          String fk = String.valueOf(forbidden.get(i));
          if (observations.containsKey(fk)) throw new AssertionError("DRIFT forbid_keys violation: " + fk);
        }
      }
      List<Object> allowed = asList(rel.get("allowed_keys"));
      if (allowed != null) {
        Set<String> allowSet = new HashSet<String>();
        for (int i = 0; i < allowed.size(); i++) allowSet.add(String.valueOf(allowed.get(i)));
        for (Iterator<String> kit = observations.keySet().iterator(); kit.hasNext(); ) {
          String ok = kit.next();
          if (!allowSet.contains(ok)) throw new AssertionError("DRIFT allowed_keys violation: " + ok);
        }
      }
    }
    Object actual = extractObservedValue(key, observations, projThen, contractId, caseId, expected);
    if (expected instanceof Map && isRelationalTable((Map<String, Object>) expected)) {
      checkRelationalBounds(contractId, caseId, key, (Map<String, Object>) expected, actual);
      return;
    }
    if (!valuesEqual(expected, actual)) {
      throw new AssertionError("DRIFT mismatch on " + contractId + "." + caseId + "." + key);
    }
  }

  private static boolean isRelationalTable(Map<String, Object> m) {
    return m.containsKey("min") || m.containsKey("max") || m.containsKey("in")
        || m.containsKey("not_in") || m.containsKey("min_len") || m.containsKey("max_len")
        || m.containsKey("allowed_keys") || m.containsKey("forbid_keys");
  }

  private static void checkRelationalBounds(
      String contractId, String caseId, String key, Map<String, Object> rel, Object actual) {
    String loc = contractId + "." + caseId + "." + key;
    if (rel.containsKey("min") && toDouble(actual) + 1e-9 < toDouble(rel.get("min"))) {
      throw new AssertionError("DRIFT min violation on " + loc);
    }
    if (rel.containsKey("max") && toDouble(actual) - 1e-9 > toDouble(rel.get("max"))) {
      throw new AssertionError("DRIFT max violation on " + loc);
    }
    if (rel.containsKey("in")) {
      List<Object> dom = asList(rel.get("in"));
      boolean found = false;
      if (dom != null) {
        for (int i = 0; i < dom.size(); i++) {
          if (valuesEqual(dom.get(i), actual)) { found = true; break; }
        }
      }
      if (!found) throw new AssertionError("DRIFT in violation on " + loc);
    }
    if (rel.containsKey("not_in")) {
      List<Object> excl = asList(rel.get("not_in"));
      if (excl != null) {
        for (int i = 0; i < excl.size(); i++) {
          if (valuesEqual(excl.get(i), actual)) throw new AssertionError("DRIFT not_in violation on " + loc);
        }
      }
    }
    if (rel.containsKey("min_len") && valueLength(actual) < toLong(rel.get("min_len"))) {
      throw new AssertionError("DRIFT min_len violation on " + loc);
    }
    if (rel.containsKey("max_len") && valueLength(actual) > toLong(rel.get("max_len"))) {
      throw new AssertionError("DRIFT max_len violation on " + loc);
    }
  }

  private static Object extractObservedValue(
      String key, Map<String, Object> observations, Map<String, Object> projThen,
      String contractId, String caseId, Object expected) {
    if (observations.containsKey(key)) return observations.get(key);
    if (projThen != null && projThen.containsKey(key)) {
      String rawPtr = String.valueOf(projThen.get(key));
      int colon = rawPtr.indexOf(":/");
      String ptr = colon >= 0 ? rawPtr.substring(colon + 1) : rawPtr;
      if (ptr.startsWith("/") && observations.containsKey(ptr.substring(1))) {
        return observations.get(ptr.substring(1));
      }
    }
    if (expected instanceof Map) {
      Map<String, Object> rel = asMap(expected);
      if (rel != null && (rel.containsKey("forbid_keys") || rel.containsKey("allowed_keys")) && rel.size() == 1) {
        return observations;
      }
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
      String prop = System.getProperty("drift.events");
      if (prop == null || prop.trim().length() == 0) prop = System.getenv("DRIFT_EVENTS");
      this.eventsFile = prop != null && prop.trim().length() > 0 ? new File(prop.trim()) : null;
    }

    private static String keyOf(Description d) { return d == null ? "" : (d.getClassName() + "#" + d.getMethodName()); }

    private void recordDesc(Description d) {
      if (d != null && d.getClassName() != null && d.getMethodName() != null) {
        classes.add(d.getClassName());
        tests.add(keyOf(d));
      }
    }

    @Override
    public void testRunStarted(Description description) { collectInventory(description); }

    private void collectInventory(Description desc) {
      if (desc == null) return;
      if (desc.isTest()) recordDesc(desc);
      ArrayList<Description> children = desc.getChildren();
      if (children != null) {
        for (int i = 0; i < children.size(); i++) collectInventory(children.get(i));
      }
    }

    @Override
    public void testStarted(Description description) {
      outcomesByTest.put(keyOf(description), "passed");
      currentVerifiedSet().clear();
      recordDesc(description);
    }

    @Override
    public void testFailure(Failure failure) { outcomesByTest.put(keyOf(failure.getDescription()), "failed"); }

    @Override
    public void testAssumptionFailure(Failure failure) {
      String k = keyOf(failure.getDescription());
      if (!"failed".equals(outcomesByTest.get(k))) outcomesByTest.put(k, "skipped");
    }

    @Override
    public void testIgnored(Description description) {
      recordDesc(description);
      emitEventForDescription(description, "disabled", Collections.<String>emptySet());
    }

    @Override
    public void testFinished(Description description) {
      Set<String> verified = new HashSet<String>(currentVerifiedSet());
      currentVerifiedSet().clear();
      String out = outcomesByTest.remove(keyOf(description));
      emitEventForDescription(description, out != null ? out : "passed", verified);
    }

    private void emitEventForDescription(Description description, String outcome, Set<String> verified) {
      Case ann = findCaseAnnotation(description);
      if (ann == null || ann.value() == null || ann.value().length == 0) return;
      String contractId = ann.contract();
      String[] rawCases = ann.value();
      List<String> caseList = new ArrayList<String>();
      List<String> readList = new ArrayList<String>();
      for (int i = 0; i < rawCases.length; i++) {
        String c = rawCases[i];
        caseList.add(c);
        if ("passed".equals(outcome) && verified.contains(contractId + ":" + c)) readList.add(c);
      }
      String digest = String.valueOf(loadResolvedView(contractId).get("digest"));
      String testId = keyOf(description);
      StringBuilder sb = new StringBuilder(256);
      sb.append("{\"cases\":"); appendStringArray(sb, caseList);
      sb.append(",\"contract\":\"").append(escapeJson(contractId)).append("\"");
      sb.append(",\"digest\":\"").append(escapeJson(digest)).append("\"");
      sb.append(",\"level\":\"").append(escapeJson(ann.level())).append("\"");
      sb.append(",\"outcome\":\"").append(escapeJson(outcome)).append("\"");
      if (!readList.isEmpty()) { sb.append(",\"read\":"); appendStringArray(sb, readList); }
      sb.append(",\"test\":\"").append(escapeJson(testId)).append("\"}");
      eventLines.add(sb.toString());
    }

    private Case findCaseAnnotation(Description description) {
      Case direct = description.getAnnotation(Case.class);
      if (direct != null) return direct;
      try { return Class.forName(description.getClassName()).getDeclaredMethod(description.getMethodName()).getAnnotation(Case.class); }
      catch (Exception e) { return null; }
    }

    @Override
    public void testRunFinished(Result result) throws Exception {
      if (eventsFile == null) return;
      File parent = eventsFile.getParentFile();
      if (parent != null && !parent.exists()) parent.mkdirs();
      StringBuilder evOut = new StringBuilder();
      for (int i = 0; i < eventLines.size(); i++) evOut.append(eventLines.get(i)).append('\n');
      writeUtf8Atomic(eventsFile, evOut.toString());
      List<String> sortedClasses = new ArrayList<String>(classes); Collections.sort(sortedClasses);
      List<String> sortedTests = new ArrayList<String>(tests); Collections.sort(sortedTests);
      StringBuilder meta = new StringBuilder(256);
      meta.append("{\n  \"classes\": "); appendStringArray(meta, sortedClasses);
      meta.append(",\n  \"tests\": "); appendStringArray(meta, sortedTests);
      meta.append(",\n  \"version\": 1\n}\n");
      writeUtf8Atomic(sidecarFor(eventsFile), meta.toString());
    }
  }

  private static File sidecarFor(File eventsFile) {
    String name = eventsFile.getName();
    String base = name.endsWith(".jsonl") ? name.substring(0, name.length() - 6) : name;
    return new File(eventsFile.getParentFile(), base + ".meta.json");
  }

  private static void writeUtf8Atomic(File target, String content) throws IOException {
    File tmp = new File(target.getParentFile(), target.getName() + ".tmp");
    OutputStreamWriter w = new OutputStreamWriter(new FileOutputStream(tmp), "UTF-8");
    try { w.write(content); } finally { w.close(); }
    if (target.exists()) target.delete();
    if (!tmp.renameTo(target)) {
      OutputStreamWriter direct = new OutputStreamWriter(new FileOutputStream(target), "UTF-8");
      try { direct.write(content); } finally { direct.close(); }
      tmp.delete();
    }
  }

  private static void appendStringArray(StringBuilder sb, List<String> items) {
    sb.append('[');
    for (int i = 0; i < items.size(); i++) {
      if (i > 0) sb.append(',');
      sb.append('"').append(escapeJson(items.get(i))).append('"');
    }
    sb.append(']');
  }

  private static String escapeJson(String s) {
    StringBuilder sb = new StringBuilder(s.length() + 8);
    for (int i = 0; i < s.length(); i++) {
      char c = s.charAt(i);
      if (c == '"' || c == '\\') sb.append('\\').append(c);
      else if (c == '\n') sb.append("\\n");
      else if (c == '\r') sb.append("\\r");
      else if (c == '\t') sb.append("\\t");
      else if (c < 0x20) {
        String hex = Integer.toHexString(c);
        sb.append("\\u00").append(hex.length() == 1 ? "0" + hex : hex);
      } else sb.append(c);
    }
    return sb.toString();
  }

  private static Map<String, Object> loadResolvedView(String contractId) {
    synchronized (VIEW_CACHE) {
      if (VIEW_CACHE.containsKey(contractId)) return VIEW_CACHE.get(contractId);
      String dir = System.getProperty("drift.resolved");
      if (dir == null || dir.trim().length() == 0) dir = System.getenv("DRIFT_RESOLVED");
      if (dir == null || dir.trim().length() == 0) {
        throw new IllegalStateException("DRIFT: missing drift.resolved / DRIFT_RESOLVED");
      }
      File f = new File(new File(dir.trim()), contractId + ".json");
      Map<String, Object> map = asMap(new MiniJson(readUtf8(f)).parse());
      if (map == null) throw new IllegalStateException("DRIFT: invalid resolved JSON in " + f);
      VIEW_CACHE.put(contractId, map);
      return map;
    }
  }

  private static String readUtf8(File f) {
    try {
      BufferedReader r = new BufferedReader(new InputStreamReader(new FileInputStream(f), "UTF-8"));
      try {
        StringBuilder sb = new StringBuilder();
        char[] buf = new char[2048];
        int n;
        while ((n = r.read(buf)) >= 0) sb.append(buf, 0, n);
        return sb.toString();
      } finally {
        r.close();
      }
    } catch (IOException e) {
      throw new IllegalStateException("DRIFT: cannot read " + f + ": " + e.getMessage(), e);
    }
  }

  @SuppressWarnings("unchecked")
  private static Map<String, Object> asMap(Object o) { return o instanceof Map ? (Map<String, Object>) o : null; }

  @SuppressWarnings("unchecked")
  private static List<Object> asList(Object o) { return o instanceof List ? (List<Object>) o : null; }

  private static double toDouble(Object o) {
    if (o instanceof Number) return ((Number) o).doubleValue();
    throw new AssertionError("DRIFT: expected numeric value, got " + o);
  }

  private static long toLong(Object o) {
    if (o instanceof Number) return ((Number) o).longValue();
    throw new AssertionError("DRIFT: expected integer value, got " + o);
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
      if ((a instanceof Long || a instanceof Integer) && (b instanceof Long || b instanceof Integer)) {
        return ((Number) a).longValue() == ((Number) b).longValue();
      }
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
    private final String s;
    private int pos;
    MiniJson(String s) { this.s = s; }
    Object parse() { skipWs(); Object v = readValue(); skipWs(); return v; }
    private void skipWs() {
      while (pos < s.length() && " \t\n\r".indexOf(s.charAt(pos)) >= 0) pos++;
    }
    private Object readValue() {
      skipWs();
      char c = s.charAt(pos);
      if (c == '{') return readObject();
      if (c == '[') return readArray();
      if (c == '"') return readString();
      if (c == 't' && s.startsWith("true", pos)) { pos += 4; return Boolean.TRUE; }
      if (c == 'f' && s.startsWith("false", pos)) { pos += 5; return Boolean.FALSE; }
      if (c == 'n' && s.startsWith("null", pos)) { pos += 4; return null; }
      return readNumber();
    }
    private Map<String, Object> readObject() {
      pos++;
      Map<String, Object> m = new LinkedHashMap<String, Object>();
      skipWs();
      if (s.charAt(pos) == '}') { pos++; return m; }
      while (true) {
        skipWs(); String k = readString(); skipWs();
        if (s.charAt(pos++) != ':') throw new IllegalStateException("Expected ':' at " + pos);
        m.put(k, readValue()); skipWs();
        char c = s.charAt(pos++);
        if (c == '}') return m;
        if (c != ',') throw new IllegalStateException("Expected ',' or '}' at " + pos);
      }
    }
    private List<Object> readArray() {
      pos++;
      List<Object> list = new ArrayList<Object>();
      skipWs();
      if (s.charAt(pos) == ']') { pos++; return list; }
      while (true) {
        list.add(readValue()); skipWs();
        char c = s.charAt(pos++);
        if (c == ']') return list;
        if (c != ',') throw new IllegalStateException("Expected ',' or ']' at " + pos);
      }
    }
    private String readString() {
      pos++;
      StringBuilder sb = new StringBuilder();
      while (pos < s.length()) {
        char c = s.charAt(pos++);
        if (c == '"') return sb.toString();
        if (c == '\\') {
          char esc = s.charAt(pos++);
          if (esc == '"' || esc == '\\' || esc == '/') sb.append(esc);
          else if (esc == 'n') sb.append('\n');
          else if (esc == 'r') sb.append('\r');
          else if (esc == 't') sb.append('\t');
          else if (esc == 'b') sb.append('\b');
          else if (esc == 'f') sb.append('\f');
          else if (esc == 'u') { sb.append((char) Integer.parseInt(s.substring(pos, pos + 4), 16)); pos += 4; }
        } else sb.append(c);
      }
      throw new IllegalStateException("Unterminated string");
    }
    private Number readNumber() {
      int start = pos;
      boolean isFloat = false;
      while (pos < s.length()) {
        char c = s.charAt(pos);
        if ((c >= '0' && c <= '9') || c == '-' || c == '+') pos++;
        else if (c == '.' || c == 'e' || c == 'E') { isFloat = true; pos++; }
        else break;
      }
      String num = s.substring(start, pos);
      return isFloat ? (Number) Double.valueOf(num) : (Number) Long.valueOf(num);
    }
  }
}
