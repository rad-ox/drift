package drift.junit4;
import java.io.*;
import java.lang.annotation.*;
import java.util.*;
import org.junit.runner.*;
import org.junit.runner.notification.*;

@SuppressWarnings({"unchecked", "rawtypes"})
public final class DriftJUnit4 {
private DriftJUnit4() {}
public interface Replayer { Map<String, Object> execute(Map<String, Object> whenWitness) throws Exception; }
@Retention(RetentionPolicy.RUNTIME) @Target(ElementType.METHOD)
public @interface Case { String contract(); String[] value(); String level() default "unit"; }
private static final Set CAPABILITIES = csvSet(
 "allowed_keys,case_frames,counterexample_replay,forbid_keys,inventory_sidecar,junit4_runner,not_in,predicates,projections,relational_bounds");
private static final Set REL_KEYS = csvSet(
 "min,max,in,not_in,len,min_len,max_len,non_empty,prefix,suffix,contains,allowed_keys,forbid_keys,monotonic,"
 + "step_max_delta,sum_total,approx,abs_tol,rel_tol,balance_fields,unit,unit_conversion,convert_from,le_field,ge_field,eq_field,sum_fields,eq");
private static final ThreadLocal<Set> VERIFIED = new InheritableThreadLocal<Set>() {
 @Override protected Set initialValue() { return new HashSet(); }
};
private static final Map<String, Map<String, Object>> CACHE = new HashMap();
private static Set csvSet(String csv) { return new TreeSet(Arrays.asList(csv.split(","))); }
private static Map<String, Object> mapOf(Object... kv) {
 Map m = new LinkedHashMap();
 for (int i = 0; i < kv.length; i += 2) m.put("" + kv[i], kv[i + 1]);
 return m;
}
private static void req(boolean ok, String m) { if (!ok) throw new AssertionError("DRIFT " + m); }
private static IllegalStateException err(String m) { return new IllegalStateException(m); }
public static void clearCache() { synchronized (CACHE) { CACHE.clear(); } }
public static Map<String, Object> bridgeCapabilities() {
 return mapOf("bridge", "drift-junit4-legacy", "capabilities", new ArrayList(CAPABILITIES),
  "runtime_baseline", "java-8-legacy", "schema", "drift.bridge-capabilities/1", "version", "0.9.1");
}
public static void requireCapabilities(Collection<String> r) {
 if (r == null) throw err("bridge.capability_unsupported:null");
 for (String c : r) { String k = c == null ? "" : c.trim(); if (k.isEmpty() || !CAPABILITIES.contains(k)) throw err("bridge.capability_unsupported:" + k); }
}
public static int replayCounterexamples(String cid, String caseId, File cex, Replayer rep, Map<String, Map<String, Object>> frames) throws Exception {
 if (cex == null) return 0;
 File[] raw = cex.isDirectory() ? cex.listFiles() : new File[] { cex };
 if (raw == null) return 0;
 Arrays.sort(raw);
 int n = 0;
 for (File f : raw) {
  if (!f.isFile() || !f.getName().endsWith(".cex.json")) continue;
  Map d = readJsonMap(f);
  if (d == null || !cid.equals(d.get("contract"))) continue;
  Object tc = d.get("case");
  if (tc instanceof String && !((String) tc).isEmpty() && !caseId.equals(tc)) continue;
  Map<String, Object> wIn = subMap(subMap(d, "witness"), "when");
  if (wIn == null) throw err("DRIFT: missing witness.when in " + f);
  verify(cid, caseId, rep.execute(wIn), frames);
  n++;
 }
 return n;
}
public static void verify(String cid, String caseId, Map<String, Object> obs) { verify(cid, caseId, obs, null); }
public static void verify(String cid, String caseId, Map<String, Object> obs, Map<String, Map<String, Object>> frames) {
 req(obs != null, cid);
 Map v = loadView(cid), cm = subMap(subMap(v, "cases"), caseId);
 req(cm != null && !cm.containsKey("status"), caseId);
 Map tm = subMap(cm, "then"), pt = subMap(subMap(v, "projections"), "then");
 Map schThen = subMap(subMap(v, "schema"), "then"), units = subMap(v, "units"), when = subMap(cm, "when");
 boolean is03 = "0.3".equals(v.get("drift"));
 if (tm != null) for (Object ko : tm.keySet()) {
  String k = "" + ko;
  Map ps = subMap(schThen, k);
  chkPred(cid + "." + caseId + "." + k, k, is03 ? unwrap03(tm.get(ko), units, ps == null ? null : ps.get("unit")) : tm.get(ko), obs, pt, when);
 }
 List sw = subList(subMap(v, "scope"), "writes"), cw = cm.containsKey("writes") ? subList(cm, "writes") : null;
 List allow = cw != null ? cw : (sw != null ? sw : Collections.emptyList());
 boolean ok = true;
 if (sw != null && cw != null) for (Object o : sw) {
  String res = "" + o, b = baseRes(res);
  if (writeAllowed(res, allow)) continue;
  Map fo = frames == null ? null : (frames.containsKey(res) ? frames.get(res) : frames.get(b));
  if (fo == null || !chkFrame(fo, res)) ok = false;
 }
 if (frames != null) for (String k : frames.keySet()) if (!writeAllowed(k, allow) && frames.get(k) != null) chkFrame(frames.get(k), k);
 if (ok) VERIFIED.get().add(cid + ":" + caseId);
}
private static String baseRes(String r) { int h = r.indexOf('#'); return h < 0 ? r : r.substring(0, h); }
private static boolean writeAllowed(String res, List allowed) {
 String b = baseRes(res); boolean unpart = res.indexOf('#') < 0;
 for (Object o : allowed) { String w = "" + o; if (w.equals(res) || w.equals(b) || (unpart && baseRes(w).equals(res))) return true; }
 return false;
}
private static boolean chkFrame(Map f, String t) {
 boolean c = false;
 if (f.containsKey("writes")) { c = true; req(toLong(f.get("writes")) == 0L, t); }
 if (f.containsKey("before") && f.containsKey("after")) { c = true; req(eqVal(f.get("before"), f.get("after")), t); }
 return !Boolean.FALSE.equals(f.get("observed")) && c;
}
private static boolean hasKey(Object val, String fk, boolean root) {
 if (val instanceof List) { for (Object x : (List) val) if (hasKey(x, fk, false)) return true; return false; }
 if (!(val instanceof Map)) return false;
 Map m = (Map) val;
 for (Object ko : m.keySet()) {
  String k = "" + ko; Object v = m.get(ko);
  if (fk.equals(k) || (!(root && "_frame".equals(k) && !"_frame".equals(fk) && v instanceof Map) && hasKey(v, fk, false))) return true;
 }
 return false;
}
private static void cpPairs(Map s, Map d, String... kv) {
 if (s != null) for (int i = 0; i < kv.length; i += 2) if (s.containsKey(kv[i])) d.put(kv[i + 1], s.get(kv[i]));
}
private static Object unwrap03(Object raw, Map units, Object pu) {
 if (!(raw instanceof Map)) return raw;
 Map m = (Map) raw;
 if (m.size() == 1 && m.containsKey("eq") && !(m.get("eq") instanceof Map)) return m.get("eq");
 Map o = mapOf();
 for (Object ko : m.keySet()) {
  String k = "" + ko; Object v = m.get(ko); Map vm = asMap(v);
  if ("eq".equals(k)) o.put(m.containsKey("tol") ? "approx" : "eq", v);
  else if ("len".equals(k)) cpPairs(vm, o, "min", "min_len", "max", "max_len");
  else if ("keys".equals(k)) cpPairs(vm, o, "allow", "allowed_keys", "forbid", "forbid_keys");
  else if ("tol".equals(k)) cpPairs(vm, o, "abs", "abs_tol", "rel", "rel_tol");
  else if ("peer".equals(k)) cpPairs(vm, o, "le", "le_field", "ge", "ge_field", "eq", "eq_field", "sum", "sum_fields", "balance", "balance_fields");
  else if ("series".equals(k) && vm != null) for (Object sk : vm.keySet()) {
   Object sv = vm.get(sk);
   o.put("" + sk, "monotonic".equals(sk) && ("increasing".equals(sv) || "decreasing".equals(sv)) ? "strictly_" + sv : sv);
  } else if (!"convert_from".equals(k)) o.put(k, v);
 }
 if (m.containsKey("convert_from")) {
  String f = "" + m.get("convert_from"), pfx = f + '-' + '>';
  Map rs = units == null ? asMap(m.get("unit_conversion")) : units;
  Object t = pu == null ? m.get("unit") : pu, r = f.equals(t) ? 1.0 : (rs != null && t != null ? rs.get(pfx + t) : null);
  if (rs != null && r == null && t == null) for (Object uk : rs.keySet()) if (("" + uk).startsWith(pfx)) r = r == null ? rs.get(uk) : -1.0;
  double sc = num(r); req(sc > 0, f);
  for (String sk : "eq,approx,min,max,abs_tol,step_max_delta,in,not_in,sum_total".split(","))
   if (o.containsKey(sk)) o.put(sk, scaleUnit(o.get(sk), sc, "approx".equals(sk) || "abs_tol".equals(sk) || "step_max_delta".equals(sk)));
 }
 return o;
}
private static Object scaleUnit(Object v, double sc, boolean forceFloat) {
 if (v instanceof Number) {
  double d = num(v) * sc;
  return !forceFloat && isIntNum(v) && d == Math.rint(d) && Math.abs(d) <= 9007199254740991.0 ? (Object) (long) d : d;
 }
 if (v instanceof List) { List s = new ArrayList(); for (Object x : (List) v) s.add(scaleUnit(x, sc, forceFloat)); return s; }
 if (v instanceof Map) { Map s = mapOf(), m = (Map) v; for (Object k : m.keySet()) s.put("" + k, scaleUnit(m.get(k), sc, forceFloat)); return s; }
 return v;
}
private static boolean hasEq(Collection items, Object target) {
 if (items != null) for (Object x : items) if (eqVal(x, target)) return true;
 return false;
}
private static double peerSum(List refs, Map obs, Map pt, Map when) {
 double tot = 0; if (refs != null) for (Object r : refs) tot += num(peerVal(obs, pt, when, r)); return tot;
}
private static void chkPred(String loc, String key, Object exp, Map obs, Map pt, Map when) {
 Object act = obsVal(key, obs, pt, loc, exp), v;
 if (!(exp instanceof Map)) { req(eqVal(exp, act), loc); return; }
 Map rel = (Map) exp;
 List forb = subList(rel, "forbid_keys"), allow = subList(rel, "allowed_keys");
 if (forb != null) { for (Object f : forb) req(!hasKey(act, "" + f, act == obs), key); }
 else if (rel.get("forbid_keys") instanceof String) req(hasKey(act, (String) rel.get("forbid_keys"), act == obs), key);
 if (allow != null) {
  req(act instanceof Map, key);
  for (Object ko : ((Map) act).keySet()) { String ok = "" + ko; if (!(act == obs && "_frame".equals(ok) && obs.get(ok) instanceof Map)) req(hasEq(allow, ok), ok); }
 }
 if (rel.isEmpty() || !REL_KEYS.containsAll(rel.keySet())) { req(eqVal(exp, act), loc); return; }
 for (Object rk : rel.keySet()) if (!"eq".equals(rk)) req(rel.get(rk) != null, loc);
 if (rel.containsKey("eq")) req(eqVal(act, rel.get("eq")), loc);
 boolean ser = rel.containsKey("monotonic") || rel.containsKey("sum_total") || rel.containsKey("step_max_delta");
 double tol = numOr(rel, "abs_tol", 1e-9);
 if ((v = rel.get("approx")) != null) {
  double ap = num(v);
  req(Math.abs(num(act) - ap) <= numOr(rel, "abs_tol", 0) + numOr(rel, "rel_tol", 0) * Math.abs(ap), loc);
 }
 if (!ser) chkIv(act, rel, tol, loc);
 for (String fk : "le_field,ge_field,eq_field".split(",")) if ((v = rel.get(fk)) != null) {
  Object p = peerVal(obs, pt, when, v);
  req("eq_field".equals(fk) ? eqVal(act, p) : ("le_field".equals(fk) ? num(act) - tol <= num(p) : num(act) + tol >= num(p)), loc);
 }
 if ((v = rel.get("sum_fields")) != null) {
  List refs = asList(v);
  req(refs != null && refs.size() >= 2 && Math.abs(num(act) - peerSum(refs, obs, pt, when)) <= tol, loc);
 }
 if ((v = rel.get("balance_fields")) != null) {
  Map bal = asMap(v);
  req(bal != null && Math.abs(num(act) - peerSum(subList(bal, "add"), obs, pt, when) + peerSum(subList(bal, "sub"), obs, pt, when)) <= tol, loc);
 }
 if (ser) {
  List vals = asList(act);
  if (vals == null && act instanceof Map && !rel.containsKey("monotonic") && !rel.containsKey("step_max_delta")) vals = new ArrayList(((Map) act).values());
  req(vals != null && !vals.isEmpty(), loc);
  double tot = 0, prev = 0;
  for (int i = 0; i < vals.size(); i++) {
   double cur = num(vals.get(i)), d = cur - prev; tot += cur; chkIv(vals.get(i), rel, tol, loc);
   if (i > 0) {
    if ((v = rel.get("step_max_delta")) != null) { double md = num(v); req(md > 0 && Math.abs(d) <= md + tol, loc); }
    if ((v = rel.get("monotonic")) != null) {
     String m = "" + v;
     req("non_decreasing".equals(m) ? d >= -tol : "non_increasing".equals(m) ? d <= tol
      : "strictly_increasing".equals(m) ? d > tol : "strictly_decreasing".equals(m) && d < -tol, loc);
    }
   }
   prev = cur;
  }
  if ((v = rel.get("sum_total")) != null) {
   Map b = asMap(v);
   req(b == null ? Math.abs(tot - num(v)) <= tol : (!b.containsKey("eq") || Math.abs(tot - num(b.get("eq"))) <= tol), loc);
   if (b != null) chkIv(tot, b, tol, loc);
  }
 }
 if ((v = rel.get("in")) != null) req(hasEq(asList(v), act), loc);
 if ((v = rel.get("not_in")) != null) { List ex = asList(v); req(act != null && (ex == null || !hasEq(ex, act)), loc); }
 if ((v = rel.get("len")) != null) req(valLen(act) == toLong(v), loc);
 if ((v = rel.get("min_len")) != null) req(valLen(act) >= toLong(v), loc);
 if ((v = rel.get("max_len")) != null) req(valLen(act) <= toLong(v), loc);
 if ((v = rel.get("non_empty")) != null) req((valLen(act) > 0) == Boolean.TRUE.equals(v), loc);
 if ((v = rel.get("prefix")) != null) req(act instanceof String && ((String) act).startsWith("" + v), loc);
 if ((v = rel.get("suffix")) != null) req(act instanceof String && ((String) act).endsWith("" + v), loc);
 if ((v = rel.get("contains")) != null) {
  req(act instanceof String || act instanceof List, loc);
  for (Object r : (v instanceof List ? (List) v : Collections.singletonList(v)))
   req(act instanceof String ? (r instanceof String && ((String) act).contains((String) r)) : hasEq((List) act, r), loc);
 }
}
private static void chkIv(Object act, Map rel, double tol, String loc) {
 if (rel.containsKey("min")) req(num(act) + tol >= num(rel.get("min")), loc);
 if (rel.containsKey("max")) req(num(act) - tol <= num(rel.get("max")), loc);
}
private static Object peerVal(Map obs, Map pt, Map when, Object raw) {
 req(raw instanceof String, "peer");
 String ref = (String) raw;
 if (ref.startsWith("when.")) {
  String k = ref.substring(5); Map in = subMap(obs, obs.get("when") != null ? "when" : "before");
  if (obs.containsKey(ref)) return obs.get(ref);
  if (in != null && in.containsKey(k)) return in.get(k);
  req(when != null && when.containsKey(k), ref);
  return unwrap03(when.get(k), null, null);
 }
 if (ref.startsWith("then.")) ref = ref.substring(5);
 return ref.startsWith("/") ? ptrVal(obs, ref) : obsVal(ref, obs, pt, "peer", null);
}
private static Object obsVal(String key, Map obs, Map pt, String loc, Object exp) {
 if (obs.containsKey(key)) return obs.get(key);
 if (pt != null && pt.containsKey(key)) return ptrVal(obs, "" + pt.get(key));
 Map rel = asMap(exp); req(rel != null && (rel.containsKey("forbid_keys") || rel.containsKey("allowed_keys")), loc); return obs;
}
private static Object ptrVal(Object cur, String raw) {
 int col = raw.indexOf(":/"); String ptr = col >= 0 ? raw.substring(col + 1) : raw;
 if (ptr.isEmpty()) return cur;
 req(ptr.startsWith("/"), raw);
 for (String s : ptr.substring(1).split("/", -1)) {
  String seg = s.replace("~1", "/").replace("~0", "~");
  if (cur instanceof Map && ((Map) cur).containsKey(seg)) cur = ((Map) cur).get(seg);
  else if (cur instanceof List) {
   int idx = -1; try { idx = Integer.parseInt(seg); } catch (NumberFormatException ignored) {}
   List l = (List) cur; req(idx >= 0 && String.valueOf(idx).equals(seg) && idx < l.size(), raw); cur = l.get(idx);
  } else req(false, raw);
 }
 return cur;
}
private static String cfg(String k) {
 for (String v : new String[] { System.getProperty("drift." + k), System.getenv("DRIFT_" + k.toUpperCase(Locale.ROOT)), sessionField(k) })
  if (v != null && !v.trim().isEmpty()) return v.trim();
 return null;
}
public static final class Listener extends RunListener {
 private final File ef;
 private final Set cls = new TreeSet(), tst = new TreeSet();
 private final List<String> evs = new ArrayList();
 private final Map<String, String> outMap = new HashMap();
 public Listener(File ef) { this.ef = ef; }
 public Listener() { String p = cfg("events"); this.ef = p != null ? new File(p) : null; }
 private static String keyOf(Description d) { return d == null ? "" : d.getClassName() + "#" + d.getMethodName(); }
 private void rec(Description d) { if (d != null && d.getClassName() != null && d.getMethodName() != null) { cls.add(d.getClassName()); tst.add(keyOf(d)); } }
 private void inv(Description d) { if (d != null) { if (d.isTest()) rec(d); if (d.getChildren() != null) for (Description c : d.getChildren()) inv(c); } }
 @Override public void testRunStarted(Description d) { inv(d); }
 @Override public void testStarted(Description d) { outMap.put(keyOf(d), "passed"); VERIFIED.get().clear(); rec(d); }
 @Override public void testFailure(Failure f) { outMap.put(keyOf(f.getDescription()), "failed"); }
 @Override public void testAssumptionFailure(Failure f) {
  String k = keyOf(f.getDescription()); if (!"failed".equals(outMap.get(k))) outMap.put(k, "skipped");
 }
 @Override public void testIgnored(Description d) { rec(d); emit(d, "disabled", null); }
 @Override public void testFinished(Description d) {
  String o = outMap.remove(keyOf(d)); try { emit(d, o != null ? o : "passed", VERIFIED.get()); } finally { VERIFIED.get().clear(); }
 }
 private synchronized void emit(Description d, String out, Set ver) {
  Case a = d.getAnnotation(Case.class);
  if (a == null) try { a = Class.forName(d.getClassName()).getDeclaredMethod(d.getMethodName()).getAnnotation(Case.class); } catch (Exception ignored) {}
  if (a == null || a.value() == null || a.value().length == 0) return;
  String cid = a.contract(); Map v = loadView(cid); List rl = new ArrayList();
  if ("passed".equals(out) && ver != null) for (String c : a.value()) if (ver.contains(cid + ":" + c)) rl.add(c);
  Map ev = new TreeMap(mapOf("cases", Arrays.asList(a.value()), "contract", cid,
   "digest", "" + v.get("digest"), "level", a.level(), "outcome", out, "test", keyOf(d)));
  if ("0.3".equals(v.get("drift"))) { ev.put("capabilities", Arrays.asList("rel-keys-guard/1", "rel-series/1", "rel-tol/1")); ev.put("schema", "0.3"); }
  if (!rl.isEmpty()) ev.put("read", rl);
  evs.add(toJson(ev));
 }
 @Override public synchronized void testRunFinished(Result r) throws Exception {
  if (ef == null) return;
  StringBuilder ev = new StringBuilder(); for (String l : evs) ev.append(l).append('\n'); writeUtf8(ef, ev.toString());
  String n = ef.getName(), b = n.endsWith(".jsonl") ? n.substring(0, n.length() - 6) : n;
  writeUtf8(new File(ef.getParentFile(), b + ".meta.json"), toJson(mapOf("classes", cls, "tests", tst, "version", 1)) + "\n");
 }
}
private static String toJson(Object v) {
 if (v == null || v instanceof Number || v instanceof Boolean) return "" + v;
 if (v instanceof String) {
  String s = (String) v; StringBuilder b = new StringBuilder(s.length() + 4).append('"');
  for (int i = 0; i < s.length(); i++) {
   char c = s.charAt(i); int k = "\n\r\t\"\\".indexOf(c);
   if (k >= 0) b.append('\\').append("nrt\"\\".charAt(k));
   else if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
   else b.append(c);
  }
  return b.append('"').toString();
 }
 StringBuilder b = new StringBuilder();
 if (v instanceof Collection) {
  b.append('['); for (Object x : (Collection) v) { if (b.length() > 1) b.append(','); b.append(toJson(x)); } return b.append(']').toString();
 }
 Map m = (Map) v; b.append('{');
 for (Object k : m.keySet()) { if (b.length() > 1) b.append(','); b.append(toJson("" + k)).append(':').append(toJson(m.get(k))); }
 return b.append('}').toString();
}
private static void writeFile(File f, byte[] b) throws IOException { OutputStream o = new FileOutputStream(f); try { o.write(b); } finally { o.close(); } }
private static void writeUtf8(File t, String c) throws IOException {
 File p = t.getParentFile(), tmp = new File(p, t.getName() + ".tmp");
 if (p != null) p.mkdirs();
 byte[] b = c.getBytes("UTF-8"); writeFile(tmp, b); t.delete();
 if (!tmp.renameTo(t)) { writeFile(t, b); tmp.delete(); }
}
private static boolean isLive(Map m) {
 String n = System.getProperty("drift.nonce", "");
 if (!n.isEmpty() && n.equals(m.get("nonce"))) return true;
 long wp = m.get("maven_pid") instanceof Number ? ((Number) m.get("maven_pid")).longValue() : -1L;
 if (wp > 0) try {
  Class ph = Class.forName("java.lang.ProcessHandle");
  for (Object c = ph.getMethod("current").invoke(null); c != null; c = ((Optional) ph.getMethod("parent").invoke(c)).orElse(null))
   if ((Long) ph.getMethod("pid").invoke(c) == wp) return true;
 } catch (Exception ignored) {}
 return false;
}
private static String sessionField(String k) {
 File sf = new File(System.getProperty("drift.session", "target/drift/session.json"));
 if (!sf.isFile()) return null;
 try {
  Map m = readJsonMap(sf);
  Object v = m != null && "drift.jvm-session/1".equals(m.get("schema")) && isLive(m) ? m.get(k) : null;
  return v instanceof String ? (String) v : null;
 } catch (RuntimeException e) { return null; }
}
private static Map<String, Object> loadView(String cid) {
 synchronized (CACHE) {
  if (CACHE.containsKey(cid)) return CACHE.get(cid);
  String d = cfg("resolved"); if (d == null) throw err("DRIFT_RESOLVED");
  Map<String, Object> m = readJsonMap(new File(d, cid + ".json")); if (m == null) throw err("JSON");
  CACHE.put(cid, m); return m;
 }
}
private static Map<String, Object> readJsonMap(File f) { return asMap(new MiniJson(readUtf8(f)).parse()); }
private static String readUtf8(File f) {
 try {
  byte[] b = new byte[(int) f.length()]; DataInputStream in = new DataInputStream(new FileInputStream(f));
  try { in.readFully(b); return new String(b, "UTF-8"); } finally { in.close(); }
 } catch (IOException e) { throw err(e.getMessage()); }
}
private static Map<String, Object> asMap(Object o) { return o instanceof Map ? (Map<String, Object>) o : null; }
private static List asList(Object o) { return o instanceof List ? (List) o : null; }
private static Map<String, Object> subMap(Map m, String k) { return m == null ? null : asMap(m.get(k)); }
private static List subList(Map m, String k) { return m == null ? null : asList(m.get(k)); }
private static boolean isIntNum(Object o) { return o instanceof Long || o instanceof Integer; }
private static double numOr(Map m, String k, double def) { return m.containsKey(k) ? num(m.get(k)) : def; }
private static double num(Object o) {
 if (o instanceof Number) { double d = ((Number) o).doubleValue(); if (Double.isFinite(d)) return d; }
 req(false, ": number " + o); return 0;
}
private static long toLong(Object o) { double d = num(o); req(d >= 0 && d == Math.rint(d), ": int " + o); return ((Number) o).longValue(); }
private static long valLen(Object o) {
 if (o instanceof String) return ((String) o).codePointCount(0, ((String) o).length());
 if (o instanceof Collection) return ((Collection) o).size();
 if (o instanceof Map) return ((Map) o).size();
 req(false, ": len " + o); return 0;
}
private static boolean eqVal(Object a, Object b) {
 if (a == b) return true;
 if (a == null || b == null) return false;
 if (a instanceof Number && b instanceof Number)
  return isIntNum(a) && isIntNum(b) ? ((Number) a).longValue() == ((Number) b).longValue()
   : Math.abs(((Number) a).doubleValue() - ((Number) b).doubleValue()) <= 1e-9;
 if (a instanceof List && b instanceof List) {
  List x = (List) a, y = (List) b; if (x.size() != y.size()) return false;
  for (int i = 0; i < x.size(); i++) if (!eqVal(x.get(i), y.get(i))) return false;
  return true;
 }
 if (a instanceof Map && b instanceof Map) {
  Map x = (Map) a, y = (Map) b; if (x.size() != y.size()) return false;
  for (Object k : x.keySet()) if (!y.containsKey(k) || !eqVal(x.get(k), y.get(k))) return false;
  return true;
 }
 return a.equals(b);
}
private static final class MiniJson {
 private final String s; private int p;
 MiniJson(String s) { this.s = s; }
 Object parse() { return val(); }
 private void ws() { while (p < s.length() && " \t\n\r".indexOf(s.charAt(p)) >= 0) p++; }
 private Object val() {
  ws(); char c = s.charAt(p);
  if (c == '{' || c == '[') {
   boolean obj = c == '{'; char end = obj ? '}' : ']'; p++; ws();
   Object out = obj ? mapOf() : new ArrayList();
   if (s.charAt(p) == end) { p++; return out; }
   for (;;) {
    if (obj) { ws(); String k = str(); ws(); if (s.charAt(p++) != ':') throw err(":"); ((Map) out).put(k, val()); }
    else ((List) out).add(val());
    ws(); char x = s.charAt(p++); if (x == end) return out; if (x != ',') throw err(",");
   }
  }
  if (c == '"') return str();
  if (s.startsWith("true", p)) { p += 4; return true; }
  if (s.startsWith("false", p)) { p += 5; return false; }
  if (s.startsWith("null", p)) { p += 4; return null; }
  int st = p; boolean fl = false;
  while (p < s.length()) {
   char x = s.charAt(p);
   if ((x >= '0' && x <= '9') || x == '-' || x == '+') p++;
   else if (x == '.' || x == 'e' || x == 'E') { fl = true; p++; }
   else break;
  }
  String n = s.substring(st, p);
  return fl ? (Object) Double.parseDouble(n) : Long.parseLong(n);
 }
 private String str() {
  p++; StringBuilder b = new StringBuilder();
  for (char c; (c = s.charAt(p++)) != '"'; ) {
   if (c != '\\') b.append(c);
   else {
    char e = s.charAt(p++); int k = "nrtbf".indexOf(e);
    if (e == 'u') { b.append((char) Integer.parseInt(s.substring(p, p + 4), 16)); p += 4; }
    else b.append(k >= 0 ? "\n\r\t\b\f".charAt(k) : e);
   }
  }
  return b.toString();
 }
}
}
