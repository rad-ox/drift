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
private static final Set<String> CAPABILITIES = new HashSet<String>(Arrays.asList("allowed_keys,case_frames,counterexample_replay,forbid_keys,inventory_sidecar,junit4_runner,not_in,predicates,projections,relational_bounds".split(",")));
private static void req(boolean ok, String m) { if (!ok) throw new AssertionError("DRIFT " + m); }
private static IllegalStateException err(String m) { return new IllegalStateException(m); }
public static Map<String, Object> bridgeCapabilities() {
 List<String> c = new ArrayList<String>(CAPABILITIES); Collections.sort(c);
 Map<String, Object> o = new LinkedHashMap<String, Object>();
 o.put("bridge", "drift-junit4-legacy"); o.put("capabilities", c); o.put("runtime_baseline", "java-8-legacy"); o.put("schema", "drift.bridge-capabilities/1"); o.put("version", "0.7.0"); return o;
}
public static void requireCapabilities(Collection<String> r) {
 if (r == null) throw err("bridge.capability_unsupported:null");
 for (String c : r) { String k = c == null ? "" : c.trim(); if (k.isEmpty() || !CAPABILITIES.contains(k)) throw err("bridge.capability_unsupported:" + k); }
}
public static int replayCounterexamples(String cid, String caseId, File cex, Replayer rep, Map<String, Map<String, Object>> frames) throws Exception {
 if (cex == null || !cex.exists()) return 0;
 List<File> fs = new ArrayList<File>();
 if (cex.isDirectory()) { File[] ch = cex.listFiles(); if (ch != null) { for (File f : ch) if (f.isFile() && f.getName().endsWith(".cex.json")) fs.add(f); Collections.sort(fs); } }
 else if (cex.getName().endsWith(".cex.json")) fs.add(cex);
 int n = 0;
 for (File f : fs) {
  Map<String, Object> d = asMap(new MiniJson(readUtf8(f)).parse());
  if (d == null || !cid.equals(d.get("contract"))) continue;
  Object tc = d.get("case"); if (tc instanceof String && !((String) tc).isEmpty() && !caseId.equals(tc)) continue;
  Map<String, Object> wit = asMap(d.get("witness")), wIn = wit != null ? asMap(wit.get("when")) : null;
  if (wIn == null) throw err("DRIFT: missing witness.when in " + f);
  verify(cid, caseId, rep.execute(wIn), frames); n++;
 }
 return n;
}
@Retention(RetentionPolicy.RUNTIME) @Target(ElementType.METHOD)
public @interface Case { String contract(); String[] value(); String level() default "unit"; }
private static final InheritableThreadLocal<Set<String>> VERIFIED = new InheritableThreadLocal<Set<String>>();
private static final Map<String, Map<String, Object>> CACHE = new HashMap<String, Map<String, Object>>();
public static void clearCache() { synchronized (CACHE) { CACHE.clear(); } }
private static Set<String> vSet() { Set<String> s = VERIFIED.get(); if (s == null) { s = new HashSet<String>(); VERIFIED.set(s); } return s; }
public static void verify(String cid, String caseId, Map<String, Object> obs) { verify(cid, caseId, obs, null); }
@SuppressWarnings("unchecked")
public static void verify(String cid, String caseId, Map<String, Object> obs, Map<String, Map<String, Object>> frames) {
 req(obs != null, cid);
 Map<String, Object> v = loadView(cid), cases = asMap(v.get("cases"));
 req(cases != null && cases.containsKey(caseId), caseId);
 Map<String, Object> cm = asMap(cases.get(caseId)); req(!cm.containsKey("status"), caseId);
 Map<String, Object> tm = asMap(cm.get("then")), pr = asMap(v.get("projections")), pt = pr != null ? asMap(pr.get("then")) : null;
 boolean is03 = "0.3".equals(v.get("drift"));
 if (tm != null) for (Map.Entry<String, Object> e : tm.entrySet()) {
  Map<String, Object> sch = asMap(v.get("schema")), ts = sch == null ? null : asMap(sch.get("then")), ps = ts == null ? null : asMap(ts.get(e.getKey()));
  chkPred(cid, caseId, e.getKey(), is03 ? unwrap03(e.getValue(), asMap(v.get("units")), ps == null ? null : ps.get("unit")) : e.getValue(), obs, pt, asMap(cm.get("when")));
 }
 Map<String, Object> sc = asMap(v.get("scope"));
 List<Object> sw = sc != null ? asList(sc.get("writes")) : null, cw = cm.containsKey("writes") ? asList(cm.get("writes")) : null;
 Set<String> aw = new HashSet<String>(), ab = new HashSet<String>(), cr = new HashSet<String>();
 for (Object o : (cw != null ? cw : (sw != null ? sw : Collections.emptyList()))) { String w = "" + o; int h = w.indexOf('#'); aw.add(w); ab.add(h >= 0 ? w.substring(0, h) : w); }
 boolean ok = true;
 if (sw != null && cw != null) for (Object o : sw) {
  String res = "" + o; int h = res.indexOf('#'); String b = h >= 0 ? res.substring(0, h) : res;
  if (aw.contains(res) || aw.contains(b) || (h < 0 && ab.contains(res))) continue;
  cr.add(res); cr.add(b);
  Map<String, Object> fo = frames != null ? (frames.containsKey(res) ? frames.get(res) : frames.get(b)) : null;
  if (fo == null || !chkFrame(fo, res)) ok = false;
 }
 if (frames != null) for (Map.Entry<String, Map<String, Object>> fe : frames.entrySet()) {
  String k = fe.getKey(); int h = k.indexOf('#'); String b = h >= 0 ? k.substring(0, h) : k;
  if (!cr.contains(k) && !aw.contains(k) && !aw.contains(b) && !(h < 0 && ab.contains(k)) && fe.getValue() != null) chkFrame(fe.getValue(), k);
 }
 if (ok) vSet().add(cid + ":" + caseId);
}
private static boolean chkFrame(Map<String, Object> f, String t) {
 boolean c = false;
 if (f.containsKey("writes")) { c = true; req(toLong(f.get("writes")) == 0L, t); }
 if (f.containsKey("before") && f.containsKey("after")) { c = true; req(eqVal(f.get("before"), f.get("after")), t); }
 return !Boolean.FALSE.equals(f.get("observed")) && c;
}
private static boolean hasKey(Object val, String fk, boolean root) {
 if (val instanceof List) { for (Object x : (List<?>) val) if (hasKey(x, fk, false)) return true; return false; }
 if (!(val instanceof Map)) return false;
 for (Map.Entry<?, ?> e : ((Map<?, ?>) val).entrySet()) {
  String k = "" + e.getKey();
  if (fk.equals(k) || (!(root && "_frame".equals(k) && !"_frame".equals(fk) && e.getValue() instanceof Map) && hasKey(e.getValue(), fk, false))) return true;
 }
 return false;
}
private static Object unwrap03(Object raw, Map<String, Object> units, Object pu) {
 if (!(raw instanceof Map)) return raw;
 @SuppressWarnings("unchecked") Map<String, Object> m = (Map<String, Object>) raw;
 if (m.size() == 1 && m.containsKey("eq") && !(m.get("eq") instanceof Map)) return m.get("eq");
 Map<String, Object> o = new LinkedHashMap<String, Object>();
 for (Map.Entry<String, Object> e : m.entrySet()) {
  String k = e.getKey(); Object v = e.getValue(); Map<?, ?> vm = v instanceof Map ? (Map<?, ?>) v : null;
  if ("eq".equals(k)) o.put(m.containsKey("tol") ? "approx" : "eq", v);
  else if ("len".equals(k) && vm != null) { cp(vm, "min", o, "min_len"); cp(vm, "max", o, "max_len"); }
  else if ("keys".equals(k) && vm != null) { cp(vm, "allow", o, "allowed_keys"); cp(vm, "forbid", o, "forbid_keys"); }
  else if ("tol".equals(k) && vm != null) { cp(vm, "abs", o, "abs_tol"); cp(vm, "rel", o, "rel_tol"); }
  else if ("series".equals(k) && vm != null) { for (Map.Entry<?, ?> se : vm.entrySet()) { Object sv = se.getValue(); if ("monotonic".equals(se.getKey()) && ("increasing".equals(sv) || "decreasing".equals(sv))) sv = "strictly_" + sv; o.put("" + se.getKey(), sv); } }
  else if ("peer".equals(k) && vm != null) { for (String pk : Arrays.asList("le", "ge", "eq")) cp(vm, pk, o, pk + "_field"); cp(vm, "sum", o, "sum_fields"); cp(vm, "balance", o, "balance_fields"); }
  else if (!"convert_from".equals(k)) o.put(k, v);
 }
 if (m.containsKey("convert_from")) {
  String f = "" + m.get("convert_from"); Object t = pu == null ? m.get("unit") : pu, r = f.equals(t) ? 1.0 : null;
  Map<String, Object> rs = units == null ? asMap(m.get("unit_conversion")) : units;
  if (rs != null && r == null) {
   if (t != null) r = rs.get(f + '-' + '>' + t);
   else { int c = 0; for (Map.Entry<String, Object> ue : rs.entrySet()) if (ue.getKey().startsWith(f + '-' + '>')) { c++; r = ue.getValue(); } if (c != 1) r = null; }
  }
  double sc = num(r); req(sc > 0, f);
  for (String sk : Arrays.asList("eq", "approx", "min", "max", "abs_tol", "step_max_delta")) if (o.get(sk) instanceof Number) o.put(sk, num(o.get(sk)) * sc);
  for (String sk : Arrays.asList("in", "not_in")) { List<Object> vs = asList(o.get(sk)); if (vs != null) { List<Object> s = new ArrayList<Object>(); for (Object x : vs) s.add(x instanceof Number ? num(x) * sc : x); o.put(sk, s); } }
  Object st = o.get("sum_total");
  if (st instanceof Number) o.put("sum_total", num(st) * sc);
  else if (st instanceof Map) { Map<String, Object> s = new LinkedHashMap<String, Object>(); for (Map.Entry<?, ?> se : ((Map<?, ?>) st).entrySet()) s.put("" + se.getKey(), se.getValue() instanceof Number ? num(se.getValue()) * sc : se.getValue()); o.put("sum_total", s); }
 }
 return o;
}
private static void cp(Map<?, ?> s, String sk, Map<String, Object> d, String dk) { if (s.containsKey(sk)) d.put(dk, s.get(sk)); }
@SuppressWarnings("unchecked")
private static void chkPred(String cid, String caseId, String key, Object exp, Map<String, Object> obs, Map<String, Object> pt, Map<String, Object> when) {
 Object act = obsVal(key, obs, pt, cid, caseId, exp);
 if (exp instanceof Map) {
  Map<String, Object> rel = (Map<String, Object>) exp;
  List<Object> forb = asList(rel.get("forbid_keys")), allow = asList(rel.get("allowed_keys"));
  if (forb != null) { for (Object f : forb) req(!hasKey(act, "" + f, act == obs), key); }
  else if (rel.get("forbid_keys") instanceof String) req(hasKey(act, (String) rel.get("forbid_keys"), act == obs), key);
  if (allow != null) { req(act instanceof Map, key); Set<String> aSet = new HashSet<String>(); for (Object a : allow) aSet.add("" + a); for (String ok : ((Map<String, Object>) act).keySet()) if (!(act == obs && "_frame".equals(ok) && obs.get(ok) instanceof Map)) req(aSet.contains(ok), ok); }
 }
 if (exp instanceof Map && isRel((Map<String, Object>) exp)) { chkRel(cid + "." + caseId + "." + key, (Map<String, Object>) exp, act, obs, pt, when); return; }
 req(eqVal(exp, act), cid + "." + caseId + "." + key);
}
private static final Set<String> REL_KEYS = new HashSet<String>(Arrays.asList("min", "max", "in", "not_in", "len", "min_len", "max_len", "non_empty", "prefix", "suffix", "contains", "allowed_keys", "forbid_keys", "monotonic", "step_max_delta", "sum_total", "approx", "abs_tol", "rel_tol", "balance_fields", "unit", "unit_conversion", "convert_from", "le_field", "ge_field", "eq_field", "sum_fields", "eq"));
private static boolean isRel(Map<String, Object> m) { return m != null && !m.isEmpty() && REL_KEYS.containsAll(m.keySet()); }
private static void chkRel(String loc, Map<String, Object> rel, Object act, Map<String, Object> obs, Map<String, Object> pt, Map<String, Object> when) {
 if (rel.containsKey("eq")) req(eqVal(act, rel.get("eq")), loc);
 boolean ser = rel.containsKey("monotonic") || rel.containsKey("sum_total") || rel.containsKey("step_max_delta");
 double tol = rel.containsKey("abs_tol") ? num(rel.get("abs_tol")) : 1e-9;
 if (rel.containsKey("approx")) { double ap = num(rel.get("approx")), at = rel.containsKey("abs_tol") ? num(rel.get("abs_tol")) : 0, rt = rel.containsKey("rel_tol") ? num(rel.get("rel_tol")) : 0; req(Math.abs(num(act) - ap) <= at + rt * Math.abs(ap), loc); }
 if (!ser) chkIv(act, rel, tol, loc);
 for (String fk : "le_field,ge_field,eq_field".split(",")) if (rel.containsKey(fk)) { Object p = peerVal(obs, pt, when, rel.get(fk)); req("eq_field".equals(fk) ? eqVal(act, p) : ("le_field".equals(fk) ? num(act) - tol <= num(p) : num(act) + tol >= num(p)), loc); }
 if (rel.containsKey("sum_fields")) { List<Object> refs = asList(rel.get("sum_fields")); req(refs != null && refs.size() >= 2, loc); double tot = 0; for (Object r : refs) tot += num(peerVal(obs, pt, when, r)); req(Math.abs(num(act) - tot) <= tol, loc); }
 if (rel.containsKey("balance_fields")) { Map<String, Object> bal = asMap(rel.get("balance_fields")); req(bal != null, loc); double tot = 0; for (String s : "add,sub".split(",")) { List<Object> refs = asList(bal.get(s)); if (refs != null) for (Object r : refs) tot += ("sub".equals(s) ? -1 : 1) * num(peerVal(obs, pt, when, r)); } req(Math.abs(num(act) - tot) <= tol, loc); }
 if (ser) {
  List<Object> vals = asList(act);
  if (vals == null && act instanceof Map && !rel.containsKey("monotonic") && !rel.containsKey("step_max_delta")) vals = new ArrayList<Object>(((Map<?, ?>) act).values());
  req(vals != null && !vals.isEmpty(), loc);
  double tot = 0, prev = 0;
  for (int i = 0; i < vals.size(); i++) {
   double cur = num(vals.get(i)); tot += cur; chkIv(vals.get(i), rel, tol, loc);
   if (i > 0) {
    if (rel.containsKey("step_max_delta")) { double d = num(rel.get("step_max_delta")); req(d > 0 && Math.abs(cur - prev) <= d + tol, loc); }
    if (rel.containsKey("monotonic")) {
     String m = String.valueOf(rel.get("monotonic"));
     req("non_decreasing".equals(m) ? prev - tol <= cur : "non_increasing".equals(m) ? prev + tol >= cur : "strictly_increasing".equals(m) ? prev + tol < cur : "strictly_decreasing".equals(m) && prev - tol > cur, loc);
    }
   }
   prev = cur;
  }
  if (rel.containsKey("sum_total")) {
   Object st = rel.get("sum_total"); Map<String, Object> b = asMap(st);
   req(b == null ? Math.abs(tot - num(st)) <= tol : (!b.containsKey("eq") || Math.abs(tot - num(b.get("eq"))) <= tol), loc);
   if (b != null) chkIv(tot, b, tol, loc);
  }
 }
 if (rel.containsKey("in")) { List<Object> dom = asList(rel.get("in")); boolean hit = false; if (dom != null) for (Object d : dom) if (eqVal(d, act)) { hit = true; break; } req(hit, loc); }
 if (rel.containsKey("not_in")) { req(act != null, loc); List<Object> ex = asList(rel.get("not_in")); if (ex != null) for (Object x : ex) req(!eqVal(x, act), loc); }
 if (rel.containsKey("len")) req(valLen(act) == toLong(rel.get("len")), loc);
 if (rel.containsKey("min_len")) req(valLen(act) >= toLong(rel.get("min_len")), loc);
 if (rel.containsKey("max_len")) req(valLen(act) <= toLong(rel.get("max_len")), loc);
 if (rel.containsKey("non_empty")) req(Boolean.TRUE.equals(rel.get("non_empty")) ? valLen(act) > 0L : valLen(act) == 0L, loc);
 if (rel.containsKey("prefix")) req(act instanceof String && ((String) act).startsWith("" + rel.get("prefix")), loc);
 if (rel.containsKey("suffix")) req(act instanceof String && ((String) act).endsWith("" + rel.get("suffix")), loc);
 if (rel.containsKey("contains")) {
  Object ce = rel.get("contains"); List<?> rl = ce instanceof List ? (List<?>) ce : Collections.singletonList(ce);
  if (act instanceof String) for (Object sub : rl) req(sub instanceof String && ((String) act).contains((String) sub), loc);
  else if (act instanceof List) { List<?> al = (List<?>) act; for (Object r : rl) { boolean hit = false; for (Object a : al) if (eqVal(a, r)) { hit = true; break; } req(hit, loc); } }
  else req(false, loc);
 }
}
private static void chkIv(Object act, Map<String, Object> rel, double tol, String loc) {
 if (rel.containsKey("min")) req(num(act) + tol >= num(rel.get("min")), loc);
 if (rel.containsKey("max")) req(num(act) - tol <= num(rel.get("max")), loc);
}
private static Object peerVal(Map<String, Object> obs, Map<String, Object> pt, Map<String, Object> when, Object raw) {
 req(raw instanceof String, "peer"); String ref = (String) raw;
 if (ref.startsWith("when.")) {
  String k = ref.substring(5); Map<String, Object> in = asMap(obs.get("when") != null ? obs.get("when") : obs.get("before"));
  if (obs.containsKey(ref)) return obs.get(ref);
  if (in != null && in.containsKey(k)) return in.get(k);
  if (when != null && when.containsKey(k)) return unwrap03(when.get(k), null, null);
  req(false, ref);
 }
 if (ref.startsWith("then.")) ref = ref.substring(5);
 return ref.startsWith("/") ? ptrVal(obs, ref) : obsVal(ref, obs, pt, "peer", "", null);
}
private static Object obsVal(String key, Map<String, Object> obs, Map<String, Object> pt, String cid, String caseId, Object exp) {
 if (obs.containsKey(key)) return obs.get(key);
 if (pt != null && pt.containsKey(key)) return ptrVal(obs, "" + pt.get(key));
 Map<String, Object> rel = asMap(exp);
 if (rel != null && (rel.containsKey("forbid_keys") || rel.containsKey("allowed_keys"))) return obs;
 req(false, cid + "." + caseId + "." + key); return null;
}
private static Object ptrVal(Object root, String raw) {
 int col = raw.indexOf(":/"); String ptr = col >= 0 ? raw.substring(col + 1) : raw;
 if (ptr.isEmpty()) return root;
 req(ptr.startsWith("/"), raw); Object cur = root;
 for (String s : ptr.substring(1).split("/", -1)) {
  String seg = s.replace("~1", "/").replace("~0", "~");
  if (cur instanceof Map && ((Map<?, ?>) cur).containsKey(seg)) cur = ((Map<?, ?>) cur).get(seg);
  else if (cur instanceof List) {
   try { int idx = Integer.parseInt(seg); if (idx < 0 || !String.valueOf(idx).equals(seg) || idx >= ((List<?>) cur).size()) throw new NumberFormatException(); cur = ((List<?>) cur).get(idx); }
   catch (NumberFormatException e) { req(false, raw); }
  } else req(false, raw);
 }
 return cur;
}
private static String nz(String... vs) { for (String v : vs) if (v != null && !v.trim().isEmpty()) return v.trim(); return null; }
public static final class Listener extends RunListener {
 private final File ef;
 private final Set<String> cls = Collections.synchronizedSet(new HashSet<String>()), tst = Collections.synchronizedSet(new HashSet<String>());
 private final List<String> evs = Collections.synchronizedList(new ArrayList<String>());
 private final Map<String, String> outMap = new ConcurrentHashMap<String, String>();
 public Listener(File ef) { this.ef = ef; }
 public Listener() { String p = nz(System.getProperty("drift.events"), System.getenv("DRIFT_EVENTS"), sessionField("events")); this.ef = p != null ? new File(p) : null; }
 private static String keyOf(Description d) { return d == null ? "" : (d.getClassName() + "#" + d.getMethodName()); }
 private void rec(Description d) { if (d != null && d.getClassName() != null && d.getMethodName() != null) { cls.add(d.getClassName()); tst.add(keyOf(d)); } }
 @Override public void testRunStarted(Description d) { inv(d); }
 private void inv(Description d) { if (d != null) { if (d.isTest()) rec(d); if (d.getChildren() != null) for (Description c : d.getChildren()) inv(c); } }
 @Override public void testStarted(Description d) { outMap.put(keyOf(d), "passed"); vSet().clear(); rec(d); }
 @Override public void testFailure(Failure f) { outMap.put(keyOf(f.getDescription()), "failed"); }
 @Override public void testAssumptionFailure(Failure f) { String k = keyOf(f.getDescription()); if (!"failed".equals(outMap.get(k))) outMap.put(k, "skipped"); }
 @Override public void testIgnored(Description d) { rec(d); emit(d, "disabled", Collections.<String>emptySet()); }
 @Override public void testFinished(Description d) { Set<String> v = new HashSet<String>(vSet()); vSet().clear(); String o = outMap.remove(keyOf(d)); emit(d, o != null ? o : "passed", v); }
 private void emit(Description d, String out, Set<String> ver) {
  Case a = d.getAnnotation(Case.class);
  if (a == null) try { a = Class.forName(d.getClassName()).getDeclaredMethod(d.getMethodName()).getAnnotation(Case.class); } catch (Exception e) {}
  if (a == null || a.value() == null || a.value().length == 0) return;
  String cid = a.contract(); Map<String, Object> v = loadView(cid);
  String dig = "" + v.get("digest"), tid = keyOf(d); boolean is03 = "0.3".equals(v.get("drift"));
  List<String> cl = new ArrayList<String>(), rl = new ArrayList<String>();
  for (String c : a.value()) { cl.add(c); if ("passed".equals(out) && ver.contains(cid + ":" + c)) rl.add(c); }
  StringBuilder sb = new StringBuilder(256).append(is03 ? "{\"capabilities\":[\"rel-keys-guard/1\",\"rel-series/1\",\"rel-tol/1\"],\"cases\":" : "{\"cases\":");
  appendArr(sb, cl);
  sb.append(",\"contract\":\"").append(esc(cid)).append("\",\"digest\":\"").append(esc(dig)).append("\",\"level\":\"").append(esc(a.level())).append("\",\"outcome\":\"").append(esc(out)).append("\"");
  if (!rl.isEmpty()) { sb.append(",\"read\":"); appendArr(sb, rl); }
  if (is03) sb.append(",\"schema\":\"0.3\"");
  evs.add(sb.append(",\"test\":\"").append(esc(tid)).append("\"}").toString());
 }
 @Override public void testRunFinished(Result r) throws Exception {
  if (ef == null) return;
  File p = ef.getParentFile(); if (p != null && !p.exists()) p.mkdirs();
  StringBuilder ev = new StringBuilder(); for (String l : evs) ev.append(l).append('\n');
  writeUtf8(ef, ev.toString());
  List<String> sc = new ArrayList<String>(cls), st = new ArrayList<String>(tst); Collections.sort(sc); Collections.sort(st);
  StringBuilder m = new StringBuilder(256).append("{\n  \"classes\": "); appendArr(m, sc); m.append(",\n  \"tests\": "); appendArr(m, st); m.append(",\n  \"version\": 1\n}\n");
  String n = ef.getName(), b = n.endsWith(".jsonl") ? n.substring(0, n.length() - 6) : n;
  writeUtf8(new File(p, b + ".meta.json"), m.toString());
 }
}
private static void writeFile(File f, byte[] b) throws IOException { OutputStream o = new FileOutputStream(f); try { o.write(b); } finally { o.close(); } }
private static void writeUtf8(File t, String c) throws IOException {
 byte[] b = c.getBytes("UTF-8"); File tmp = new File(t.getParentFile(), t.getName() + ".tmp"); writeFile(tmp, b);
 if (t.exists()) t.delete();
 if (!tmp.renameTo(t)) { writeFile(t, b); tmp.delete(); }
}
private static void appendArr(StringBuilder sb, List<String> l) {
 sb.append('['); for (int i = 0; i < l.size(); i++) { if (i > 0) sb.append(','); sb.append('"').append(esc(l.get(i))).append('"'); } sb.append(']');
}
private static String esc(String s) {
 StringBuilder b = new StringBuilder(s.length() + 8);
 for (int i = 0; i < s.length(); i++) {
  char c = s.charAt(i);
  if (c == '"' || c == '\\') b.append('\\').append(c);
  else if (c == '\n') b.append("\\n"); else if (c == '\r') b.append("\\r"); else if (c == '\t') b.append("\\t");
  else if (c < 0x20) b.append(String.format("\\u%04x", (int) c)); else b.append(c);
 }
 return b.toString();
}
private static boolean isLive(Map<String, Object> m) {
 String n = System.getProperty("drift.nonce", ""); if (!n.isEmpty() && n.equals(m.get("nonce"))) return true;
 long wp = m.get("maven_pid") instanceof Number ? ((Number) m.get("maven_pid")).longValue() : -1L; if (wp <= 0) return false;
 try {
  Class<?> ph = Class.forName("java.lang.ProcessHandle"), op = Class.forName("java.util.Optional");
  for (Object c = ph.getMethod("current").invoke(null); c != null; c = op.getMethod("orElse", Object.class).invoke(ph.getMethod("parent").invoke(c), (Object) null))
   if (((Long) ph.getMethod("pid").invoke(c)) == wp) return true;
 } catch (Exception ignored) {}
 return false;
}
private static String sessionField(String k) {
 File sf = new File(System.getProperty("drift.session", "target/drift/session.json")); if (!sf.isFile()) return null;
 try { Map<String, Object> m = asMap(new MiniJson(readUtf8(sf)).parse()); Object v = m != null && "drift.jvm-session/1".equals(m.get("schema")) && isLive(m) ? m.get(k) : null; return v instanceof String ? (String) v : null; } catch (RuntimeException e) { return null; }
}
private static Map<String, Object> loadView(String cid) {
 synchronized (CACHE) {
  if (CACHE.containsKey(cid)) return CACHE.get(cid);
  String d = nz(System.getProperty("drift.resolved"), System.getenv("DRIFT_RESOLVED"), sessionField("resolved")); if (d == null) throw err("DRIFT_RESOLVED");
  Map<String, Object> m = asMap(new MiniJson(readUtf8(new File(d, cid + ".json"))).parse()); if (m == null) throw err("JSON");
  CACHE.put(cid, m); return m;
 }
}
private static String readUtf8(File f) {
 try {
  InputStream in = new FileInputStream(f);
  try { ByteArrayOutputStream o = new ByteArrayOutputStream(); byte[] b = new byte[2048]; int n; while ((n = in.read(b)) >= 0) o.write(b, 0, n); return o.toString("UTF-8"); } finally { in.close(); }
 } catch (IOException e) { throw err(e.getMessage()); }
}
@SuppressWarnings("unchecked") private static Map<String, Object> asMap(Object o) { return o instanceof Map ? (Map<String, Object>) o : null; }
@SuppressWarnings("unchecked") private static List<Object> asList(Object o) { return o instanceof List ? (List<Object>) o : null; }
private static double num(Object o) { if (o instanceof Number) { double d = ((Number) o).doubleValue(); if (!Double.isNaN(d) && !Double.isInfinite(d)) return d; } req(false, ": number " + o); return 0; }
private static long toLong(Object o) { if (o instanceof Number) { double d = ((Number) o).doubleValue(); if (!Double.isNaN(d) && !Double.isInfinite(d) && d >= 0 && d == Math.rint(d)) return ((Number) o).longValue(); } req(false, ": int " + o); return 0; }
private static long valLen(Object o) { if (o instanceof String) return ((String) o).codePointCount(0, ((String) o).length()); if (o instanceof Collection) return ((Collection<?>) o).size(); if (o instanceof Map) return ((Map<?, ?>) o).size(); req(false, ": len " + o); return 0; }
private static boolean eqVal(Object a, Object b) {
 if (a == b) return true; if (a == null || b == null) return false;
 if (a instanceof Number && b instanceof Number) return ((a instanceof Long || a instanceof Integer) && (b instanceof Long || b instanceof Integer)) ? ((Number) a).longValue() == ((Number) b).longValue() : Math.abs(((Number) a).doubleValue() - ((Number) b).doubleValue()) <= 1e-9;
 if (a instanceof List && b instanceof List) { List<?> x = (List<?>) a, y = (List<?>) b; if (x.size() != y.size()) return false; for (int i = 0; i < x.size(); i++) if (!eqVal(x.get(i), y.get(i))) return false; return true; }
 if (a instanceof Map && b instanceof Map) { Map<?, ?> x = (Map<?, ?>) a, y = (Map<?, ?>) b; if (x.size() != y.size()) return false; for (Map.Entry<?, ?> e : x.entrySet()) if (!y.containsKey(e.getKey()) || !eqVal(e.getValue(), y.get(e.getKey()))) return false; return true; }
 return a.equals(b);
}
private static final class MiniJson {
 private final String s; private int p;
 MiniJson(String s) { this.s = s; }
 Object parse() { ws(); Object v = val(); ws(); return v; }
 private void ws() { while (p < s.length() && " \t\n\r".indexOf(s.charAt(p)) >= 0) p++; }
 private Object val() {
  ws(); char c = s.charAt(p);
  if (c == '{') { p++; Map<String, Object> m = new LinkedHashMap<String, Object>(); ws(); if (s.charAt(p) == '}') { p++; return m; } for (;;) { ws(); String k = str(); ws(); if (s.charAt(p++) != ':') throw err(":"); m.put(k, val()); ws(); char x = s.charAt(p++); if (x == '}') return m; if (x != ',') throw err(","); } }
  if (c == '[') { p++; List<Object> l = new ArrayList<Object>(); ws(); if (s.charAt(p) == ']') { p++; return l; } for (;;) { l.add(val()); ws(); char x = s.charAt(p++); if (x == ']') return l; if (x != ',') throw err(","); } }
  if (c == '"') return str();
  if (c == 't' && s.startsWith("true", p)) { p += 4; return Boolean.TRUE; }
  if (c == 'f' && s.startsWith("false", p)) { p += 5; return Boolean.FALSE; }
  if (c == 'n' && s.startsWith("null", p)) { p += 4; return null; }
  int st = p; boolean fl = false;
  while (p < s.length()) { char x = s.charAt(p); if ((x >= '0' && x <= '9') || x == '-' || x == '+') p++; else if (x == '.' || x == 'e' || x == 'E') { fl = true; p++; } else break; }
  String n = s.substring(st, p); return fl ? (Number) Double.valueOf(n) : (Number) Long.valueOf(n);
 }
 private String str() {
  p++; StringBuilder b = new StringBuilder();
  while (p < s.length()) {
   char c = s.charAt(p++); if (c == '"') return b.toString();
   if (c == '\\') { char e = s.charAt(p++); if (e == 'u') { b.append((char) Integer.parseInt(s.substring(p, p + 4), 16)); p += 4; } else b.append(e == 'n' ? '\n' : e == 'r' ? '\r' : e == 't' ? '\t' : e == 'b' ? '\b' : e == 'f' ? '\f' : e); }
   else b.append(c);
  }
  throw err("EOF");
 }
}
}
