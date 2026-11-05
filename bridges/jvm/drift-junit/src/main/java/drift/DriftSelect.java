package drift;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.lang.reflect.Method;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.platform.engine.FilterResult;
import org.junit.platform.engine.TestDescriptor;
import org.junit.platform.engine.support.descriptor.MethodSource;
import org.junit.platform.launcher.PostDiscoveryFilter;

/**
 * Keeps only the tests chosen by {@code drift select --json}, read from the file named by the
 * system property {@code drift.select}; several files may be joined with the path separator.
 * Without the property, or when any selection widens, every test runs. Otherwise a test method
 * runs when its {@link DriftCase} names a selected case of the same contract or when its
 * {@code Class#method} is a selected test. A direct code hit or one-hop resource hit keeps every
 * tagged test of that contract; every other test, untagged ones included, is excluded. Descriptors
 * without a method source are kept and pruned by JUnit when empty.
 */
public final class DriftSelect implements PostDiscoveryFilter {
    public static final String SELECT = "drift.select";

    private final Map<String, Set<String>> casesByContract;
    private final Set<String> methods;
    private final Set<String> codeHitContracts;
    private final boolean all;

    public DriftSelect() {
        String files = Drift.mutationRun() ? null : System.getProperty(SELECT);
        String contractsProp = Drift.mutationRun()
                ? null
                : System.getProperty("drift.contracts", System.getenv().getOrDefault("DRIFT_CONTRACTS", ""));
        Map<String, Set<String>> byContract = new HashMap<>();
        Set<String> selectedMethods = new HashSet<>();
        Set<String> codeHits = new HashSet<>();
        if (contractsProp != null && !contractsProp.isBlank()) {
            for (String cid : contractsProp.split(",")) {
                if (!cid.isBlank()) {
                    codeHits.add(cid.trim());
                }
            }
        }
        boolean every = (files == null || files.isBlank()) && codeHits.isEmpty();
        if (files != null && !files.isBlank()) {
            for (String f : files.split(java.io.File.pathSeparator)) {
                if (f.isBlank()) {
                    continue;
                }
                Map<String, Object> m = object(read(Path.of(f)), f);
                if (Boolean.TRUE.equals(m.get("all"))) {
                    every = true;
                    break;
                }
                List<?> items = m.containsKey("contracts")
                        ? list(m.get("contracts"), f + ".contracts")
                        : List.of(m);
                for (Object item : items) {
                    Map<String, Object> cm = object(item, f);
                    if (Boolean.TRUE.equals(cm.get("all"))) {
                        every = true;
                        break;
                    }
                    String contract = (String) cm.get("contract");
                    if (contract != null) {
                        List<?> replayed = list(cm.get("replayed_cases"), f + ".replayed_cases");
                        if (Boolean.TRUE.equals(cm.get("code_hit"))
                                || (Boolean.TRUE.equals(cm.get("resource_hit")) && replayed.isEmpty())) {
                            codeHits.add(contract);
                        }
                        Set<String> cases = byContract.computeIfAbsent(contract, k -> new HashSet<>());
                        for (Object o : list(cm.get("cases"), f + ".cases")) {
                            cases.add((String) object(o, f + ".cases").get("case"));
                        }
                        for (Object o : replayed) {
                            cases.add((String) o);
                        }
                    }
                    for (Object o : list(cm.get("tests"), f + ".tests")) {
                        addMethod(selectedMethods, (String) o);
                    }
                }
                if (every) {
                    break;
                }
            }
        }
        this.all = every;
        this.casesByContract = Map.copyOf(byContract);
        this.methods = Set.copyOf(selectedMethods);
        this.codeHitContracts = Set.copyOf(codeHits);
    }

    private static void addMethod(Set<String> out, String test) {
        out.add(test);
        int hash = test.indexOf('#');
        if (hash > 0) {
            int i = hash + 1;
            while (i < test.length() && Character.isJavaIdentifierPart(test.charAt(i))) {
                i++;
            }
            out.add(test.substring(0, i));
        }
    }

    @Override
    public FilterResult apply(TestDescriptor d) {
        DriftListener.discovered(d);
        if (all || d.getSource().isEmpty() || !(d.getSource().get() instanceof MethodSource ms)) {
            return FilterResult.included("drift: not narrowed");
        }
        DriftCase tag;
        try {
            Method method = ms.getJavaMethod();
            tag = method.getAnnotation(DriftCase.class);
        } catch (RuntimeException e) {
            return FilterResult.included("drift: method not resolvable");
        }
        if (tag != null) {
            if (codeHitContracts.contains(tag.contract())) {
                return FilterResult.included("drift: code hit for contract " + tag.contract());
            }
            Set<String> cases = casesByContract.get(tag.contract());
            if (cases != null) {
                for (String id : tag.cases()) {
                    if (cases.contains(id)) {
                        return FilterResult.included("drift: tagged with changed case " + id);
                    }
                }
            }
        }
        String key = ms.getClassName() + "#" + ms.getMethodName();
        if (methods.contains(key)) {
            return FilterResult.included("drift: selected test " + key);
        }
        return FilterResult.excluded("drift: not selected");
    }

    private static Object read(Path file) {
        try {
            return Json.read(file);
        } catch (IOException e) {
            throw new UncheckedIOException("cannot read the selection " + file, e);
        }
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> object(Object o, String where) {
        if (o instanceof Map<?, ?> m) {
            return (Map<String, Object>) m;
        }
        throw new IllegalStateException(where + " is not a JSON object");
    }

    private static List<?> list(Object o, String where) {
        if (o == null) {
            return List.of();
        }
        if (o instanceof List<?> l) {
            return l;
        }
        throw new IllegalStateException(where + " is not a JSON array");
    }

    private static void addUniqueLong(List<Long> pts, long val) {
        if (!pts.contains(val)) {
            pts.add(val);
        }
    }

    static List<Long> intDomain(long min, long max) {
        if (min > max) {
            throw new IllegalArgumentException("invalid int domain [" + min + ", " + max + "]");
        }
        if (Drift.mutationRun()) {
            return List.of(min < 0 && max > 0 ? 0L : min);
        }
        long mid = (min / 2) + (max / 2) + ((min % 2 + max % 2) / 2);
        List<Long> pts = new ArrayList<>(6);
        if (min < 0 && max > 0) {
            pts.add(0L);
        }
        addUniqueLong(pts, min);
        if (min < max) {
            addUniqueLong(pts, min + 1);
        }
        addUniqueLong(pts, mid);
        if (max > min) {
            addUniqueLong(pts, max - 1);
        }
        addUniqueLong(pts, max);
        return List.copyOf(pts);
    }

    static List<String> enumDomain(String... values) {
        if (values == null || values.length == 0) {
            throw new IllegalArgumentException("enum domain must not be empty");
        }
        if (Drift.mutationRun()) {
            return List.of(values[0]);
        }
        LinkedHashSet<String> pts = new LinkedHashSet<>(List.of(values));
        return List.copyOf(pts);
    }

    static List<Boolean> boolDomain() {
        return Drift.mutationRun() ? List.of(Boolean.FALSE) : List.of(Boolean.FALSE, Boolean.TRUE);
    }

    static List<Map<String, Object>> cartesianDomain(Map<String, ? extends List<?>> domains) {
        if (domains == null || domains.isEmpty()) {
            throw new IllegalArgumentException("Cartesian domain map must not be empty");
        }
        List<String> keys = domains.keySet().stream().sorted().toList();
        if (Drift.mutationRun()) {
            Map<String, Object> first = new LinkedHashMap<>(keys.size());
            for (String key : keys) {
                List<?> vals = domains.get(key);
                if (vals == null || vals.isEmpty()) {
                    throw new IllegalArgumentException("domain for key " + key + " must not be empty");
                }
                first.put(key, vals.get(0));
            }
            return List.of(Collections.unmodifiableMap(first));
        }
        int d = keys.size();
        List<List<?>> valsByKey = new ArrayList<>(d);
        Map<String, Object> cur = new LinkedHashMap<>(d);
        for (String key : keys) {
            List<?> vals = domains.get(key);
            if (vals == null || vals.isEmpty()) {
                throw new IllegalArgumentException("domain for key " + key + " must not be empty");
            }
            valsByKey.add(vals);
            cur.put(key, vals.get(0));
        }
        int maxExcursions = d >= 3 ? 2 : d;
        List<Map<String, Object>> out = new ArrayList<>();
        collectSkeletonTuples(keys, valsByKey, 0, 0, maxExcursions, cur, out);
        return List.copyOf(out);
    }

    private static void collectSkeletonTuples(
            List<String> keys,
            List<List<?>> valsByKey,
            int pos,
            int exc,
            int maxExcursions,
            Map<String, Object> cur,
            List<Map<String, Object>> out) {
        if (pos == keys.size() || exc >= maxExcursions) {
            out.add(Collections.unmodifiableMap(new LinkedHashMap<>(cur)));
            return;
        }
        collectSkeletonTuples(keys, valsByKey, pos + 1, exc, maxExcursions, cur, out);
        List<?> vals = valsByKey.get(pos);
        String key = keys.get(pos);
        for (int i = 1; i < vals.size(); i++) {
            cur.put(key, vals.get(i));
            collectSkeletonTuples(keys, valsByKey, pos + 1, exc + 1, maxExcursions, cur, out);
        }
        cur.put(key, vals.get(0));
    }

    @SuppressWarnings("unchecked")
    static List<Object> profileSingleDomain(String contract, Map<String, Object> specs, String param) {
        if (param == null || param.isBlank()) {
            throw new IllegalArgumentException("profile parameter name must not be blank");
        }
        Object rawSpec = specs.get(param);
        if (rawSpec == null) {
            throw new IllegalArgumentException("contract " + contract + " has no bounded param_specs." + param);
        }
        Map<String, Object> spec = DriftInternal.map(rawSpec, contract + ".param_specs." + param);
        String type = spec.get("type") instanceof String s ? s : "";
        if ("int".equals(type)) {
            if (!(spec.get("min") instanceof Number lo) || !(spec.get("max") instanceof Number hi)) {
                throw new IllegalArgumentException("param_specs." + param + " requires numeric min and max");
            }
            return (List<Object>) (List<?>) intDomain(lo.longValue(), hi.longValue());
        }
        if ("string".equals(type) && spec.get("enum") instanceof List<?> rawEnum && !rawEnum.isEmpty()) {
            String[] values = new String[rawEnum.size()];
            for (int i = 0; i < rawEnum.size(); i++) {
                values[i] = String.valueOf(rawEnum.get(i));
            }
            return (List<Object>) (List<?>) enumDomain(values);
        }
        if ("bool".equals(type)) {
            return (List<Object>) (List<?>) boolDomain();
        }
        throw new IllegalArgumentException("unsupported param_specs." + param + " type: " + type);
    }

    static List<Object> profileDomain(String contract, String param) {
        Map<String, Object> specs = DriftInternal.map(Drift.view(contract).getOrDefault("param_specs", Map.of()),
                contract + ".param_specs");
        return profileSingleDomain(contract, specs, param);
    }

    static List<Map<String, Object>> profileDomain(String contract, java.util.Collection<String> params) {
        if (params == null || params.isEmpty()) {
            throw new IllegalArgumentException("profile parameter collection must not be empty");
        }
        Map<String, Object> specs = DriftInternal.map(Drift.view(contract).getOrDefault("param_specs", Map.of()),
                contract + ".param_specs");
        Map<String, List<Object>> domains = new LinkedHashMap<>(params.size());
        for (String param : params) {
            domains.put(param, profileSingleDomain(contract, specs, param));
        }
        return cartesianDomain(domains);
    }
}
