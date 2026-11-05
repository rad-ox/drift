package drift;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.LinkedHashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.BiConsumer;
import java.util.stream.Stream;

final class DriftInternal {
    private static final Map<Path, Map<String, Path>> TOML_DIR_CACHE = new ConcurrentHashMap<>();
    private static final Map<Path, Long> PROFILE_MTIME_CACHE = new ConcurrentHashMap<>();
    private static final Set<Path> BATCH_WARMED_DIRS = ConcurrentHashMap.newKeySet();
    private static final Map<String, Map<String, Object>> AUTO_BATCH_CACHE = new ConcurrentHashMap<>();
    private static final Map<Path, Map<String, UpstreamMatch>> UPSTREAM_CACHE = new ConcurrentHashMap<>();
    private static volatile String cachedCliKey;
    private static volatile String cachedCli;

    private DriftInternal() {}

    static String fileSignature(Path abs) {
        try {
            long size = Files.size(abs);
            long mtime = Files.getLastModifiedTime(abs).toMillis();
            return (size > 65536 ? "L:" : "S:") + mtime + ":" + size;
        } catch (IOException e) {
            throw new UncheckedIOException("cannot stat input file " + abs, e);
        }
    }

    static String sha256File(Path abs) {
        try {
            byte[] raw = Files.readAllBytes(abs);
            byte[] norm = normalizeBytes(raw);
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            return "sha256:" + HexFormat.of().formatHex(md.digest(norm));
        } catch (IOException e) {
            throw new UncheckedIOException("cannot hash input file " + abs, e);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    private static byte[] normalizeBytes(byte[] raw) {
        boolean hasCrlf = false;
        for (int i = 0; i < raw.length; i++) {
            if (raw[i] == 0) {
                return raw;
            }
            if (raw[i] == '\r' && i + 1 < raw.length && raw[i + 1] == '\n') {
                hasCrlf = true;
            }
        }
        if (!hasCrlf) {
            return raw;
        }
        byte[] tmp = new byte[raw.length];
        int pos = 0;
        for (int i = 0; i < raw.length; i++) {
            if (raw[i] == '\r' && i + 1 < raw.length && raw[i + 1] == '\n') {
                tmp[pos++] = '\n';
                i++;
            } else {
                tmp[pos++] = raw[i];
            }
        }
        byte[] out = new byte[pos];
        System.arraycopy(tmp, 0, out, 0, pos);
        return out;
    }

    record MutationOverride(
            String contract, String caseId, String path, Object value, boolean isWhen, String[] segments) {
        static MutationOverride of(String contract, String caseId, String path, Object value) {
            String escaped = escape(caseId);
            String whenPrefix = "/cases/" + escaped + "/when/";
            boolean isWhen = path.startsWith(whenPrefix);
            String section = isWhen ? "when" : "then";
            String prefix = isWhen ? whenPrefix : "/cases/" + escaped + "/then/";
            if (!path.startsWith(prefix)) {
                throw new IllegalArgumentException("mutation path " + path + " is outside "
                        + contract + "." + caseId + "." + section);
            }
            String[] rawSegments = path.substring(prefix.length()).split("/", -1);
            if (rawSegments.length == 0 || rawSegments[0].isEmpty()) {
                throw new IllegalArgumentException("mutation path " + path + " has no " + section + " leaf");
            }
            String[] unescaped = new String[rawSegments.length];
            for (int i = 0; i < rawSegments.length; i++) {
                unescaped[i] = unescape(rawSegments[i]);
            }
            return new MutationOverride(contract, caseId, path, value, isWhen, unescaped);
        }

        Map<String, Object> apply(Map<String, Object> then) {
            return replace(then, segments, 0);
        }

        Map<String, Object> applyWhen(Map<String, Object> when) {
            return replace(when, segments, 0);
        }

        private Map<String, Object> replace(Map<String, Object> table, String[] segs, int index) {
            String key = segs[index];
            if (!table.containsKey(key)) {
                throw new IllegalArgumentException("mutation path has no predicate " + key);
            }
            Map<String, Object> copy = new HashMap<>(table);
            if (index == segs.length - 1) {
                copy.put(key, value);
                return copy;
            }
            if (index == 0 && segs.length == 2 && value instanceof Map<?, ?> swapMap
                    && table.containsKey(segs[1]) && swapMap.containsKey(key) && swapMap.containsKey(segs[1])) {
                copy.put(key, swapMap.get(key));
                copy.put(segs[1], swapMap.get(segs[1]));
                return copy;
            }
            Object nested = table.get(key);
            if (!(nested instanceof Map<?, ?> raw)) {
                throw new IllegalArgumentException("mutation path crosses a non-table value at " + key);
            }
            Map<String, Object> child = new HashMap<>();
            for (Map.Entry<?, ?> entry : raw.entrySet()) {
                if (!(entry.getKey() instanceof String childKey)) {
                    throw new IllegalArgumentException("mutation path crosses a table with a non-string key");
                }
                child.put(childKey, entry.getValue());
            }
            copy.put(key, replace(child, segs, index + 1));
            return copy;
        }

        private static String escape(String value) {
            return value.replace("~", "~0").replace("/", "~1");
        }

        private static String unescape(String value) {
            return value.replace("~1", "/").replace("~0", "~");
        }
    }


    static void clearCache() {
        TOML_DIR_CACHE.clear();
        PROFILE_MTIME_CACHE.clear();
        BATCH_WARMED_DIRS.clear();
        AUTO_BATCH_CACHE.clear();
        UPSTREAM_CACHE.clear();
    }

    private static long maxSourceMtime(Path cur, Path tomlFile) {
        long max = 0L;
        try {
            if (tomlFile != null && Files.isRegularFile(tomlFile)) {
                max = Files.getLastModifiedTime(tomlFile).toMillis();
            }
            Path pDir = cur.resolve(".drift").resolve("profiles");
            long profMax = PROFILE_MTIME_CACHE.computeIfAbsent(pDir, dir -> {
                long pmMax = 0L;
                if (Files.isDirectory(dir)) {
                    try (Stream<Path> s = Files.list(dir)) {
                        for (Path pf : s.filter(p -> p.getFileName().toString().endsWith(".toml")).toList()) {
                            long pm = Files.getLastModifiedTime(pf).toMillis();
                            if (pm > pmMax) {
                                pmMax = pm;
                            }
                        }
                    } catch (IOException ignored) {
                    }
                }
                return pmMax;
            });
            if (profMax > max) {
                max = profMax;
            }
        } catch (IOException ignored) {
        }
        return max;
    }

    static Map<String, Object> autoResolve(String contract) {
        return autoResolveTarget(contract, null);
    }

    static Map<String, Object> autoResolveTarget(String contract, Path targetJson) {
        if (targetJson == null) {
            Map<String, Object> batchHit = AUTO_BATCH_CACHE.get(contract);
            if (batchHit != null) {
                return batchHit;
            }
        }
        Path cur = targetJson != null
                ? targetJson.toAbsolutePath().normalize().getParent()
                : Path.of("").toAbsolutePath().normalize();
        String userHome = System.getProperty("user.home", "");
        String localBinCli = userHome.isBlank()
                ? ""
                : Path.of(userHome, ".local", "bin", "drift").toString();
        String localAppData = System.getenv("LOCALAPPDATA");
        if ((localAppData == null || localAppData.isBlank()) && !userHome.isBlank()) {
            localAppData = Path.of(userHome, "AppData", "Local").toString();
        }
        String winBinCli = (localAppData == null || localAppData.isBlank())
                ? ""
                : Path.of(localAppData, "Programs", "drift", "bin", "drift.exe").toString();
        while (cur != null) {
            Path resolvedCandidate = null;
            if (targetJson != null) {
                if (Files.isRegularFile(targetJson)) {
                    resolvedCandidate = targetJson;
                }
            } else {
                for (Path rel : List.of(
                        Path.of(".drift", "resolved", contract + ".json"),
                        Path.of(".drift", "views", contract + ".json"),
                        Path.of(".drift-work", "resolved", contract + ".json"),
                        Path.of("target", "drift", "resolved", contract + ".json"))) {
                    Path candidate = cur.resolve(rel);
                    if (Files.isRegularFile(candidate)) {
                        resolvedCandidate = candidate;
                        break;
                    }
                }
            }
            Path tomlFile = null;
            Path contractsDir = cur.resolve(".drift").resolve("contracts");
            if (Files.isDirectory(contractsDir)) {
                Path direct = contractsDir.resolve(contract + ".toml");
                if (Files.isRegularFile(direct)) {
                    tomlFile = direct;
                } else {
                    Map<String, Path> idx = TOML_DIR_CACHE.computeIfAbsent(contractsDir, dir -> {
                        Map<String, Path> map = new HashMap<>();
                        try (Stream<Path> walk = Files.walk(dir)) {
                            walk.filter(Files::isRegularFile)
                                    .filter(p -> p.getFileName().toString().endsWith(".toml"))
                                    .sorted()
                                    .forEach(p -> {
                                        String fn = p.getFileName().toString();
                                        map.putIfAbsent(fn.substring(0, fn.length() - 5), p);
                                    });
                        } catch (IOException ignored) {
                                                    }
                        return Collections.unmodifiableMap(map);
                    });
                    Path match = idx.get(contract);
                    if (match != null && Files.isRegularFile(match)) {
                        tomlFile = match;
                    }
                }
            }
            if (targetJson != null && tomlFile == null) {
                if (Files.exists(cur.resolve(".drift")) || Files.exists(cur.resolve(".git"))) {
                    return null;
                }
                cur = cur.getParent();
                continue;
            }
            boolean resolvedFresh = false;
            if (resolvedCandidate != null) {
                if (tomlFile == null) {
                    resolvedFresh = true;
                } else {
                    try {
                        long rcMtime = Files.getLastModifiedTime(resolvedCandidate).toMillis();
                        long srcMtime = maxSourceMtime(cur, tomlFile);
                        resolvedFresh = rcMtime >= srcMtime;
                    } catch (IOException ignored) {
                        resolvedFresh = true;
                    }
                }
            }
            if (resolvedFresh) {
                try {
                    return map(Json.read(resolvedCandidate), resolvedCandidate.toString());
                } catch (IOException e) {
                    throw new UncheckedIOException("cannot read the resolved view " + resolvedCandidate, e);
                }
            }
            if (tomlFile != null) {
                String envCli = System.getenv("DRIFT_CLI");
                String envTrimmed = envCli == null ? "" : envCli.trim();
                String cliKey = envTrimmed + "\u0000" + cur;
                List<String> clis = new ArrayList<>(5);
                if (cliKey.equals(cachedCliKey) && cachedCli != null) {
                    clis.add(cachedCli);
                }
                if (!envTrimmed.isEmpty() && !clis.contains(envTrimmed)) {
                    clis.add(envTrimmed);
                }
                Path buildCli = cur.resolve(".build").resolve("drift");
                if (Files.isRegularFile(buildCli)) {
                    String s = buildCli.toString();
                    if (!clis.contains(s)) {
                        clis.add(s);
                    }
                }
                if (!clis.contains("drift")) {
                    clis.add("drift");
                }
                for (String pathCand : List.of(localBinCli, winBinCli)) {
                    if (!pathCand.isBlank() && !clis.contains(pathCand) && Files.isRegularFile(Path.of(pathCand))) {
                        clis.add(pathCand);
                    }
                }
                boolean batchWarm = targetJson == null && !BATCH_WARMED_DIRS.add(contractsDir);
                for (String cli : clis) {
                    if (batchWarm) {
                        Path tmpOut = null;
                        try {
                            tmpOut = Files.createTempDirectory("drift-resolved-");
                            Process bp = new ProcessBuilder(
                                            cli, "show", contractsDir.toString(), "--out", tmpOut.toString())
                                    .directory(cur.toFile())
                                    .start();
                            bp.getInputStream().readAllBytes();
                            bp.waitFor();
                            try (Stream<Path> stream = Files.list(tmpOut)) {
                                stream.filter(p -> p.getFileName().toString().endsWith(".json"))
                                        .forEach(p -> {
                                            String fn = p.getFileName().toString();
                                            String cid = fn.substring(0, fn.length() - 5);
                                            try {
                                                AUTO_BATCH_CACHE.put(cid, map(Json.read(p), p.toString()));
                                            } catch (IOException ignored) {
                                            }
                                        });
                            }
                            Map<String, Object> warmed = AUTO_BATCH_CACHE.get(contract);
                            if (warmed != null) {
                                cachedCliKey = cliKey;
                                cachedCli = cli;
                                return warmed;
                            }
                        } catch (IOException | InterruptedException ignored) {
                        } finally {
                            if (tmpOut != null) {
                                try (Stream<Path> s = Files.walk(tmpOut)) {
                                    s.sorted(java.util.Comparator.reverseOrder())
                                            .forEach(p -> {
                                                try {
                                                    Files.deleteIfExists(p);
                                                } catch (IOException ignored) {
                                                }
                                            });
                                } catch (IOException ignored) {
                                }
                            }
                        }
                    }
                    try {
                        Process p = new ProcessBuilder(cli, "show", tomlFile.toString(), "--as", "json")
                                .directory(cur.toFile())
                                .start();
                        String out = new String(p.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
                        if (p.waitFor() == 0 && !out.isBlank()) {
                            cachedCliKey = cliKey;
                            cachedCli = cli;
                            Map<String, Object> parsed = map(Json.parse(out), tomlFile.toString());
                            Path resolvedDir = cur.resolve(".drift").resolve("resolved");
                            Path viewsDir = cur.resolve(".drift").resolve("views");
                            Path cacheTarget = targetJson != null
                                    ? targetJson
                                    : (resolvedCandidate != null
                                            ? resolvedCandidate
                                            : (Files.isDirectory(resolvedDir)
                                                    ? resolvedDir.resolve(contract + ".json")
                                                    : (Files.isDirectory(viewsDir) ? viewsDir.resolve(contract + ".json") : null)));
                            if (cacheTarget != null) {
                                try {
                                    Files.createDirectories(cacheTarget.getParent());
                                    Files.writeString(cacheTarget, out, StandardCharsets.UTF_8);
                                } catch (IOException ignored) {
                                                                    }
                            }
                            return parsed;
                        }
                    } catch (IOException | InterruptedException ignored) {
                                            }
                }
            }
            if (resolvedCandidate != null) {
                try {
                    return map(Json.read(resolvedCandidate), resolvedCandidate.toString());
                } catch (IOException e) {
                    throw new UncheckedIOException("cannot read the resolved view " + resolvedCandidate, e);
                }
            }
            if (targetJson != null && (Files.exists(cur.resolve(".drift")) || Files.exists(cur.resolve(".git")))) {
                return null;
            }
            cur = cur.getParent();
        }
        if (targetJson != null) {
            return null;
        }
        UpstreamMatch upstream = findUpstreamContract(contract);
        if (upstream != null) {
            return upstream.view();
        }
        throw new IllegalStateException("system property " + Drift.RESOLVED + " is not set");
    }

    record UpstreamMatch(Map<String, Object> view, Path file) {}

    static UpstreamMatch findUpstreamContract(String idOrRes) {
        Path cur = Path.of("").toAbsolutePath().normalize();
        Path foundDir = null;
        while (cur != null) {
            Path cand = cur.resolve(".drift").resolve("upstream");
            if (Files.isDirectory(cand)) {
                foundDir = cand;
                break;
            }
            cur = cur.getParent();
        }
        if (foundDir == null) {
            return null;
        }
        Map<String, UpstreamMatch> idx = UPSTREAM_CACHE.computeIfAbsent(foundDir, upDir -> {
            Map<String, UpstreamMatch> map = new HashMap<>();
            try (Stream<Path> list = Files.list(upDir)) {
                for (Path fp : list.filter(p -> p.getFileName().toString().endsWith(".json")).sorted().toList()) {
                    try {
                        Object raw = Json.read(fp);
                        if (!(raw instanceof Map<?, ?> doc)) {
                            continue;
                        }
                        String area = doc.get("area") instanceof String a ? a : "";
                        List<?> cts = "boundary".equals(doc.get("kind")) && doc.get("contracts") instanceof List<?> l
                                ? l
                                : (doc.get("id") instanceof String ? List.of(doc) : List.of());
                        for (Object item : cts) {
                            if (!(item instanceof Map<?, ?> cm)) {
                                continue;
                            }
                            UpstreamMatch hit = new UpstreamMatch(map(cm, fp.toString()), fp);
                            String cid = cm.get("id") instanceof String s ? s : "";
                            if (!cid.isEmpty()) {
                                map.putIfAbsent(cid, hit);
                                if (!area.isEmpty()) {
                                    map.putIfAbsent(area + ":" + cid, hit);
                                }
                            }
                            if (cm.get("scope") instanceof Map<?, ?> sc) {
                                List<Object> resList = new ArrayList<>();
                                if (sc.get("out") instanceof List<?> o) resList.addAll(o);
                                if (sc.get("writes") instanceof List<?> w) resList.addAll(w);
                                if (sc.get("reads") instanceof List<?> rd) resList.addAll(rd);
                                for (Object r : resList) {
                                    String rs = String.valueOf(r);
                                    String base = rs.split("#", 2)[0];
                                    map.putIfAbsent(rs, hit);
                                    if (!base.isEmpty()) {
                                        map.putIfAbsent(base, hit);
                                    }
                                }
                            }
                        }
                    } catch (IOException | RuntimeException ignored) {
                    }
                }
            } catch (IOException ignored) {
            }
            return Collections.unmodifiableMap(map);
        });
        UpstreamMatch direct = idx.get(idOrRes);
        return direct != null ? direct : idx.get(idOrRes.split("#", 2)[0]);
    }

    static Map<String, Object> load(String contract, String dir) {
        Path file = Path.of(dir, contract + ".json");
        Map<String, Object> synced = autoResolveTarget(contract, file.toAbsolutePath().normalize());
        if (synced != null && contract.equals(synced.get("id"))) {
            return synced;
        }
        try {
            return map(Json.read(file), file.toString());
        } catch (IOException e) {
            throw new UncheckedIOException("cannot read the resolved view " + file, e);
        }
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> map(Object o, String where) {
        if (o instanceof Map<?, ?> m) {
            return (Map<String, Object>) m;
        }
        throw new IllegalStateException(where + " is not a JSON object");
    }


    static List<Long> intDomain(long min, long max) {
        return DriftSelect.intDomain(min, max);
    }

    static List<String> enumDomain(String... values) {
        return DriftSelect.enumDomain(values);
    }

    static List<Boolean> boolDomain() {
        return DriftSelect.boolDomain();
    }

    static List<Map<String, Object>> cartesianDomain(Map<String, ? extends List<?>> domains) {
        return DriftSelect.cartesianDomain(domains);
    }

    static List<Object> profileDomain(String contract, String param) {
        return DriftSelect.profileDomain(contract, param);
    }

    static List<Map<String, Object>> profileDomain(String contract, java.util.Collection<String> params) {
        return DriftSelect.profileDomain(contract, params);
    }

}
