package drift;

import static drift.DriftViewChecks.fail;

import java.util.*;
import static java.util.Map.entry;

/**
 * Fail-closed UI surface, WCAG 2.2 category contrast, multi-point focus obscuration,
 * and cross-platform adapter capability checks for the DRIFT JUnit bridge.
 */
final class DriftUiChecks {
    private static final Map<String, String> PREDICATE_CAPABILITY = Map.ofEntries(
            entry("min_contrast_ratio", "wcag22_contrast"),
            entry("min_contrast_wcag22", "wcag22_contrast"),
            entry("min_contrast_text_normal", "wcag22_contrast"),
            entry("min_contrast_text_large", "wcag22_contrast"),
            entry("min_contrast_ui_component", "wcag22_contrast"),
            entry("contrast_violations_count", "wcag22_contrast"),
            entry("assistive_announcement", "assistive_focus"),
            entry("active_assistive_focus", "assistive_focus"),
            entry("observed_transition_ms", "observed_transition"),
            entry("max_transition_ms", "observed_transition"),
            entry("scroll_context_preserved", "scroll_state"),
            entry("horizontal_overflow_px", "geometry"),
            entry("min_target_px", "geometry"),
            entry("clipped_elements", "geometry"),
            entry("unintentional_clipped_count", "geometry"),
            entry("obscured_focus_elements", "geometry"),
            entry("fully_obscured_focus_count", "geometry"),
            entry("partially_obscured_focus_count", "geometry"),
            entry("notice_precedes_detail", "geometry"),
            entry("after_focus_role", "input_focus"),
            entry("active_focus", "input_focus"),
            entry("trigger_restored", "input_focus"),
            entry("unexpected_focus_steals", "input_focus"));

    private DriftUiChecks() {}
    private static boolean isT(Object v) { return Boolean.TRUE.equals(v); }
    private static boolean isF(Object v) { return Boolean.FALSE.equals(v); }

    private static Object mapOr(Map<?, ?> m, String k, Object def) {
        Object v = m == null ? null : m.get(k);
        return v != null ? v : def;
    }

    private static double numberOr(Object value, double fallback) {
        return value instanceof Number n ? n.doubleValue() : fallback;
    }

    private static void checkCount(String contract, String id, String key, Object expected, long count) {
        long want = expected instanceof Number n ? n.longValue() : -1L;
        if (count != want) {
            throw fail(contract + "." + id + ": expected " + key + "=" + expected + ", got " + count);
        }
    }

    static boolean isElementHidden(Map<?, ?> el) {
        if (el == null) return false;
        String pres = String.valueOf(el.containsKey("presence") ? el.get("presence") : mapOr(el, "state", "")).trim().toLowerCase();
        if ("hidden".equals(pres) || "absent".equals(pres) || "collapsed".equals(pres)) return true;
        if (isT(el.get("hidden")) || isT(el.get("ariaHidden")) || "true".equals(String.valueOf(el.get("aria-hidden")))) return true;
        String disp = String.valueOf(mapOr(el, "display", "")).trim().toLowerCase(), vis = String.valueOf(mapOr(el, "visibility", "")).trim().toLowerCase();
        return "none".equals(disp) || "hidden".equals(vis) || "collapse".equals(vis);
    }

    static boolean isElementScrollable(Map<?, ?> el, String axis) {
        if (el == null) return false;
        if (isT(el.get("scrollable"))) return true;
        if (isF(el.get("scrollable"))) return false;
        String ox = String.valueOf(mapOr(el, "overflowX", mapOr(el, "overflow", ""))).trim().toLowerCase();
        String oy = String.valueOf(mapOr(el, "overflowY", mapOr(el, "overflow", ""))).trim().toLowerCase();
        boolean sx = "auto".equals(ox) || "scroll".equals(ox) || isT(el.get("horizontallyScrollable"));
        boolean sy = "auto".equals(oy) || "scroll".equals(oy) || isT(el.get("verticallyScrollable"));
        return "x".equals(axis) ? sx : ("y".equals(axis) ? sy : (sx || sy));
    }

    static boolean isElementUnintentionallyClipped(Map<?, ?> el) {
        if (el == null || isElementHidden(el)) return false;
        double sw = numberOr(el.get("scrollWidth"), 0.0), cw = numberOr(el.get("clientWidth"), 0.0);
        double sh = numberOr(el.get("scrollHeight"), 0.0), ch = numberOr(el.get("clientHeight"), 0.0);
        return ((sw > cw) && !isElementScrollable(el, "x")) || ((sh > ch) && !isElementScrollable(el, "y"));
    }

    static void checkAdapterCapability(String contract, String id, String key, Map<String, Object> v, Map<String, String> proj) {
        if (!(v.get("adapter") instanceof Map<?, ?> adapter) || !(adapter.get("capabilities") instanceof List<?> caps)) return;
        String ptr = proj != null ? proj.getOrDefault(key, "") : "", leaf = "";
        if (ptr != null && !ptr.isEmpty()) {
            String[] segs = ptr.split("/");
            for (int i = segs.length - 1; i >= 0; i--) if (!segs[i].isEmpty()) { leaf = segs[i]; break; }
        }
        String reqCap = PREDICATE_CAPABILITY.getOrDefault(key, PREDICATE_CAPABILITY.get(leaf));
        if (reqCap != null && !caps.contains(reqCap)) throw fail(contract + "." + id + ": ui.capability_unverifiable:" + reqCap + " for then." + key);
    }

    static boolean checkSurfaceKey(
            Drift.Case c,
            String key,
            Object expected,
            Map<String, Object> v,
            Map<String, Object> then,
            Map<String, String> thenProj) {
        String contract = c.contract();
        String id = c.id();
        List<?> rawEls = v.get("elements") instanceof List<?> l ? l : List.of();
        boolean hasSurfaceEvidence = isT(v.get("surfaceFound"))
                || isT(v.get("surface_found"))
                || !rawEls.isEmpty();
        Map<?, ?> presMap = v.get("presentation") instanceof Map<?, ?> pm ? pm : Map.of();

        if ("clipped_elements".equals(key) || "unintentional_clipped_count".equals(key)) {
            Map<?, ?> clipSub = presMap.get("clipping") instanceof Map<?, ?> cm ? cm : Map.of();
            Object expClipObj = v.containsKey(key) ? v.get(key) : clipSub.get("unintentional_clipped_count");
            if (rawEls.isEmpty() && !(expClipObj instanceof Number)) {
                throw fail(contract + "." + id + ": unverifiable then." + key + ": empty surface view");
            }
            long clipped = 0L;
            if (expClipObj instanceof Number n && rawEls.isEmpty()) {
                clipped = n.longValue();
            } else {
                for (Object item : rawEls) {
                    if (item instanceof Map<?, ?> el && isElementUnintentionallyClipped(el)) {
                        clipped++;
                    }
                }
            }
            checkCount(contract, id, key, expected, clipped);
            return true;
        }
        if ("horizontal_overflow_px".equals(key)) {
            Object expOvObj = v.containsKey("horizontal_overflow_px")
                    ? v.get("horizontal_overflow_px")
                    : presMap.get("horizontal_overflow_px");
            double vpW = numberOr(v.get("viewportWidth"), 0.0);
            boolean hasVp = vpW > 0.0 && v.get("documentWidth") instanceof Number;
            if (!hasVp && !(expOvObj instanceof Number)) {
                throw fail(contract + "." + id + ": unverifiable then.horizontal_overflow_px: missing viewportWidth");
            }
            double docW = numberOr(v.get("documentWidth"), 0.0);
            double overflow = (expOvObj instanceof Number n && !hasVp) ? n.doubleValue() : Math.max(0.0, docW - vpW);
            double want = numberOr(expected, -1.0);
            if (overflow > want) {
                throw fail(contract + "." + id + ": expected horizontal_overflow_px<=" + expected + ", got " + overflow);
            }
            return true;
        }
        if ("min_contrast_ratio".equals(key)
                || "min_contrast_wcag22".equals(key)
                || "min_contrast_text_normal".equals(key)
                || "min_contrast_text_large".equals(key)
                || "min_contrast_ui_component".equals(key)) {
            double minRatio = Double.POSITIVE_INFINITY;
            long unverifiableCount = 0L;
            for (Object item : rawEls) {
                if (item instanceof Map<?, ?> el && !isElementHidden(el)) {
                    if (isT(el.get("contrastUnverifiable"))
                            || isT(el.get("backgroundUnverifiable"))) {
                        unverifiableCount++;
                        continue;
                    }
                    if (el.get("contrastRatio") instanceof Number n) {
                        String cat = String.valueOf(mapOr(el, "contrastCategory",
                                mapOr(el, "category", "text_normal"))).trim().toLowerCase();
                        if (("min_contrast_text_normal".equals(key) && !"text_normal".equals(cat))
                                || ("min_contrast_text_large".equals(key) && !"text_large".equals(cat))
                                || ("min_contrast_ui_component".equals(key) && !"ui_component".equals(cat))) {
                            continue;
                        }
                        minRatio = Math.min(minRatio, n.doubleValue());
                    }
                }
            }
            if (unverifiableCount > 0 && !then.containsKey("contrast_unverifiable_count") && !then.containsKey("unverifiable_checks")) {
                throw fail(contract + "." + id + ": unverifiable then." + key + ": " + unverifiableCount + " element(s) have indeterminate background");
            }
            if (Double.isInfinite(minRatio)) {
                Map<?, ?> cw = presMap.get("contrast_wcag22") instanceof Map<?, ?> m ? m : Map.of();
                Object fb = v.get(key);
                if (fb == null) {
                    fb = "min_contrast_text_normal".equals(key) ? cw.get("text_normal_min")
                            : ("min_contrast_text_large".equals(key) ? cw.get("text_large_min")
                            : ("min_contrast_ui_component".equals(key) ? cw.get("ui_component_min") : v.get("min_contrast_ratio")));
                }
                if (!(fb instanceof Number n)) {
                    throw fail(contract + "." + id + ": unverifiable then." + key + ": no measured elements");
                }
                minRatio = n.doubleValue();
            }
            if (expected instanceof Map<?, ?> relMap && (relMap.containsKey("min") || relMap.containsKey("max"))) {
                DriftViewChecks.checkRelationalConstraint(c, key, relMap, minRatio, v, thenProj == null ? Map.of() : thenProj);
                return true;
            }
            double want = numberOr(expected, 21.0);
            if (minRatio < want) {
                throw fail(contract + "." + id + ": expected " + key + ">=" + expected + ", got " + minRatio);
            }
            return true;
        }
        if ("min_target_px".equals(key)) {
            double minPx = Double.POSITIVE_INFINITY;
            for (Object item : rawEls) {
                if (item instanceof Map<?, ?> el
                        && !isElementHidden(el)
                        && el.get("width") instanceof Number w
                        && el.get("height") instanceof Number h
                        && w.doubleValue() > 0.0
                        && h.doubleValue() > 0.0
                        && !isT(el.get("spacingException"))) {
                    minPx = Math.min(minPx, Math.min(w.doubleValue(), h.doubleValue()));
                }
            }
            if (Double.isInfinite(minPx)) {
                Map<?, ?> tsSub = presMap.get("target_size") instanceof Map<?, ?> m ? m : Map.of();
                Object expTarget = v.containsKey("min_target_px") ? v.get("min_target_px") : tsSub.get("min_target_size");
                if (!(expTarget instanceof Number n)) {
                    throw fail(contract + "." + id + ": unverifiable then.min_target_px: no measured elements");
                }
                minPx = n.doubleValue();
            }
            double want = numberOr(expected, 24.0);
            if (minPx < want) {
                throw fail(contract + "." + id + ": expected min_target_px>=" + expected + ", got " + minPx);
            }
            return true;
        }
        if ("obscured_focus_elements".equals(key)
                || "fully_obscured_focus_count".equals(key)
                || "partially_obscured_focus_count".equals(key)) {
            long obscured = 0L;
            boolean hasFlag = false;
            boolean checkPartial = "partially_obscured_focus_count".equals(key);
            for (Object item : rawEls) {
                if (item instanceof Map<?, ?> el && !isElementHidden(el)) {
                    boolean focusable = !el.containsKey("focusable") || isT(el.get("focusable"));
                    if (!focusable) {
                        continue;
                    }
                    if (el.get("hitPoints") instanceof List<?> pts && !pts.isEmpty()) {
                        hasFlag = true;
                        long cov = pts.stream().filter(p -> isT(p)
                                || (p instanceof Map<?, ?> pm && isT(pm.get("covered")))).count();
                        if (checkPartial ? cov > 0 : cov == pts.size()) {
                            obscured++;
                        }
                    } else if (el.get("visualOverlays") instanceof List<?> overlays && !overlays.isEmpty()
                            && el.get("width") instanceof Number ew && el.get("height") instanceof Number eh
                            && ew.doubleValue() > 0 && eh.doubleValue() > 0) {
                        hasFlag = true;
                        double w = ew.doubleValue();
                        double h = eh.doubleValue();
                        double left = numberOr(el.get("left"), numberOr(el.get("x"), 0.0));
                        double top = numberOr(el.get("top"), numberOr(el.get("y"), 0.0));
                        double ix = Math.min(2.0, w / 4.0);
                        double iy = Math.min(2.0, h / 4.0);
                        double[][] samplePts = {
                            {left + w / 2.0, top + h / 2.0},
                            {left + ix, top + iy},
                            {left + w - ix, top + iy},
                            {left + ix, top + h - iy},
                            {left + w - ix, top + h - iy}
                        };
                        long cov = 0L;
                        for (double[] pt : samplePts) {
                            for (Object ovObj : overlays) {
                                if (ovObj instanceof Map<?, ?> ov && !isElementHidden(ov)) {
                                    if (numberOr(ov.get("opacity"), 1.0) <= 0.0) {
                                        continue;
                                    }
                                    double ol = numberOr(ov.get("left"), numberOr(ov.get("x"), 0.0));
                                    double ot = numberOr(ov.get("top"), numberOr(ov.get("y"), 0.0));
                                    double ow = numberOr(ov.get("width"), 0.0);
                                    double oh = numberOr(ov.get("height"), 0.0);
                                    if (ow > 0.0 && oh > 0.0 && pt[0] >= ol && pt[0] <= ol + ow && pt[1] >= ot && pt[1] <= ot + oh) {
                                        cov++;
                                        break;
                                    }
                                }
                            }
                        }
                        if (checkPartial ? cov > 0 : cov == samplePts.length) {
                            obscured++;
                        }
                    } else if (el.containsKey("fullyObscured") || el.containsKey("partiallyObscured")
                            || el.containsKey("obscured") || el.containsKey("focusObscured")) {
                        hasFlag = true;
                        boolean full = isT(el.get("fullyObscured"))
                                || isT(el.get("obscured"))
                                || isT(el.get("focusObscured"));
                        boolean part = isT(el.get("partiallyObscured")) || full;
                        if (checkPartial ? part : full) {
                            obscured++;
                        }
                    }
                }
            }
            Map<?, ?> fvSub = presMap.get("focus_visibility") instanceof Map<?, ?> m ? m : Map.of();
            Object expFocus = v.containsKey(key)
                    ? v.get(key)
                    : fvSub.get(checkPartial ? "partially_obscured_count" : "fully_obscured_count");
            if (!hasFlag && !(expFocus instanceof Number)) {
                throw fail(contract + "." + id + ": unverifiable then." + key + ": no measured elements");
            }
            if (!hasFlag && expFocus instanceof Number n) {
                obscured = n.longValue();
            }
            checkCount(contract, id, key, expected, obscured);
            return true;
        }
        if ("unverified_elements".equals(key) || "unverifiable_checks".equals(key)) {
            Map<?, ?> evSub = v.get("evidence") instanceof Map<?, ?> m ? m : Map.of();
            Object rawU = v.containsKey("unverified_elements")
                    ? v.get("unverified_elements")
                    : (v.containsKey("unverifiable_checks")
                            ? v.get("unverifiable_checks")
                            : evSub.get("unverifiable_checks"));
            if (!(rawU instanceof Number) && rawEls.isEmpty()) {
                throw fail(contract + "." + id + ": unverifiable then." + key + ": empty surface view");
            }
            long actU = rawU instanceof Number n ? n.longValue() : 0L;
            checkCount(contract, id, key, expected, actU);
            return true;
        }
        return false;
    }

    static List<Set<String>> allowedWriteSetsOf(Map<String, Object> view, String caseId) {
        List<?> swList = (view.get("scope") instanceof Map<?, ?> sm && sm.get("writes") instanceof List<?> sl) ? sl : List.of();
        List<?> cwList = (view.get("cases") instanceof Map<?, ?> cm0 && cm0.get(caseId) instanceof Map<?, ?> cm && cm.get("writes") instanceof List<?> cl) ? cl : null;
        Set<String> allowed = new LinkedHashSet<>(), allowedBases = new LinkedHashSet<>();
        for (Object item : (cwList != null ? cwList : swList)) {
            String w = String.valueOf(item);
            allowed.add(w);
            int h = w.indexOf('#');
            allowedBases.add(h >= 0 ? w.substring(0, h) : w);
        }
        return List.of(allowed, allowedBases);
    }

    static boolean isWriteResourceAllowed(String res, Set<String> allowed, Set<String> allowedBases) {
        int h = res.indexOf('#');
        String base = h >= 0 ? res.substring(0, h) : res;
        return allowed.contains(res) || allowed.contains(base) || (h < 0 && allowedBases.contains(res));
    }

    static List<String> forbiddenWritesOf(Map<String, Object> view, String caseId) {
        if (!(view.get("scope") instanceof Map<?, ?> sm) || !(sm.get("writes") instanceof List<?> swList)
                || !(view.get("cases") instanceof Map<?, ?> cm0) || !(cm0.get(caseId) instanceof Map<?, ?> cm)
                || !(cm.get("writes") instanceof List<?>)) return List.of();
        List<Set<String>> sets = allowedWriteSetsOf(view, caseId);
        List<String> out = new ArrayList<>();
        for (Object item : swList) {
            String r = String.valueOf(item);
            if (!isWriteResourceAllowed(r, sets.get(0), sets.get(1))) out.add(r);
        }
        return out;
    }

    private static boolean isNonNegInteger(Object v) {
        if (!Json.isFiniteNumber(v)) return false;
        double d = ((Number) v).doubleValue();
        return d >= 0.0 && d == Math.rint(d) && d <= 9007199254740991.0;
    }

    private static void verifySingleFrameObs(String pfx, String res, Object obs, boolean isAmbient) {
        boolean checked = false;
        String writeLbl = (isAmbient ? "undeclared write on perimeter resource \"" : "frame violation on resource \"") + res + "\"";
        String snapLbl = (isAmbient ? "undeclared state mutation on perimeter resource \"" : "frame state mutation on resource \"") + res + "\"";
        if (isNonNegInteger(obs)) {
            checked = true;
            if (((Number) obs).longValue() > 0L) throw fail(pfx + ": " + writeLbl + ": expected 0 writes, observed " + obs);
        } else if (obs instanceof Map<?, ?> om) {
            for (String wk : new String[] {"writes", "operations", "events"}) {
                if (!om.containsKey(wk)) continue;
                Object wv = om.get(wk);
                if (isNonNegInteger(wv)) {
                    checked = true;
                    if (((Number) wv).longValue() > 0L) throw fail(pfx + ": " + writeLbl + ": expected 0 writes, observed " + wv);
                } else if (wv instanceof java.util.Collection<?> col) {
                    checked = true;
                    if (!col.isEmpty()) throw fail(pfx + ": " + writeLbl + ": expected 0 writes, observed " + col.size());
                } else {
                    throw fail(pfx + ": invalid frame " + wk + " for \"" + res + "\": expected non-negative integer, got " + wv);
                }
            }
            if (om.containsKey("before") && om.containsKey("after")) {
                checked = true;
                if (!Json.valuesEqual(om.get("before"), om.get("after"))) {
                    throw fail(pfx + ": " + snapLbl + ": before and after snapshots differ");
                }
            }
        }
        if (!checked) {
            throw fail(pfx + ": frame observation for \"" + res + "\" must supply writes/operations/events or before/after snapshots");
        }
    }

    private static boolean isUnobservedFrameEntry(Object obs) {
        return obs instanceof Map<?, ?> m && isF(m.get("observed"));
    }

    private static boolean hasFrameMetricsEntry(Object obs) {
        if (!(obs instanceof Map<?, ?> m)) {
            return false;
        }
        return m.containsKey("writes")
                || m.containsKey("operations")
                || m.containsKey("events")
                || (m.containsKey("before") && m.containsKey("after"));
    }

    static void checkFrame(Drift.Case c, Map<String, Object> frameObs) {
        checkFrame(c, frameObs, true);
    }

    static void checkFrame(Drift.Case c, Map<String, Object> frameObs, boolean strict) {
        Map<String, Object> view = Drift.view(c.contract());
        List<String> forbidden = forbiddenWritesOf(view, c.id());
        String pfx = c.contract() + "." + c.id();
        Set<String> checkedKeys = new LinkedHashSet<>();
        boolean allObserved = true;
        java.util.TreeSet<String> observedWrites = new java.util.TreeSet<>();
        try {
            for (String res : forbidden) {
                int h = res.indexOf('#');
                String baseRes = h >= 0 ? res.substring(0, h) : res;
                checkedKeys.add(res);
                checkedKeys.add(baseRes);
                Object obs = frameObs == null ? null : (frameObs.containsKey(res) ? frameObs.get(res) : frameObs.get(baseRes));
                if (hasFrameMetricsEntry(obs)) {
                    verifySingleFrameObs(pfx, res, obs, false);
                }
                if (obs == null || isUnobservedFrameEntry(obs)) {
                    allObserved = false;
                    if (strict) {
                        String msg = obs == null
                                ? "missing frame observation for forbidden write resource \"" + res + "\""
                                : "frame.observer_missing for forbidden write resource \"" + res + "\"";
                        throw fail(pfx + ": " + msg);
                    }
                    continue;
                }
                if (!hasFrameMetricsEntry(obs)) {
                    verifySingleFrameObs(pfx, res, obs, false);
                }
                Drift.mark(c.contract(), c.id(), "@frame:" + res);
            }
            if (frameObs != null) {
                List<Set<String>> sets = allowedWriteSetsOf(view, c.id());
                Set<String> allowed = sets.get(0);
                Set<String> allowedBases = sets.get(1);
                List<String> sortedKeys = new ArrayList<>();
                for (Object kObj : frameObs.keySet()) {
                    sortedKeys.add(String.valueOf(kObj));
                }
                Collections.sort(sortedKeys);
                for (String k : sortedKeys) {
                    Object obsK = frameObs.get(k);
                    if (isUnobservedFrameEntry(obsK)) {
                        allObserved = false;
                    }
                    if (DriftObservations.entryWrote(obsK)) {
                        observedWrites.add(k);
                    }
                    if (checkedKeys.contains(k) || isWriteResourceAllowed(k, allowed, allowedBases)) {
                        continue;
                    }
                    if (hasFrameMetricsEntry(obsK)) {
                        verifySingleFrameObs(pfx, k, obsK, true);
                    }
                    if (isUnobservedFrameEntry(obsK)) {
                        if (strict) {
                            throw fail(pfx + ": frame.observer_missing for perimeter resource \"" + k + "\"");
                        }
                        continue;
                    }
                    if (!hasFrameMetricsEntry(obsK)) {
                        verifySingleFrameObs(pfx, k, obsK, true);
                    }
                }
            }
            if (allObserved && (!forbidden.isEmpty() || !observedWrites.isEmpty())) {
                DriftObservations.recordFrame(c, new ArrayList<>(observedWrites));
            } else {
                DriftObservations.clearFrame(c);
            }
            DriftVerify.recordStandaloneFrameOutcome(c, true);
        } catch (Throwable err) {
            DriftObservations.clearFrame(c);
            DriftVerify.recordStandaloneFrameOutcome(c, false);
            throw err;
        }
    }
}
