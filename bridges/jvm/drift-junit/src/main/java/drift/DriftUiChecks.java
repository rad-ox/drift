package drift;

import java.util.List;
import java.util.Map;

/**
 * Fail-closed UI surface, WCAG 2.2 category contrast, multi-point focus obscuration,
 * and cross-platform adapter capability checks for the DRIFT JUnit bridge (D282-D284).
 */
final class DriftUiChecks {
    private static final Map<String, String> PREDICATE_CAPABILITY = Map.ofEntries(
            Map.entry("min_contrast_ratio", "wcag22_contrast"),
            Map.entry("min_contrast_wcag22", "wcag22_contrast"),
            Map.entry("min_contrast_text_normal", "wcag22_contrast"),
            Map.entry("min_contrast_text_large", "wcag22_contrast"),
            Map.entry("min_contrast_ui_component", "wcag22_contrast"),
            Map.entry("contrast_violations_count", "wcag22_contrast"),
            Map.entry("assistive_announcement", "assistive_focus"),
            Map.entry("active_assistive_focus", "assistive_focus"),
            Map.entry("observed_transition_ms", "observed_transition"),
            Map.entry("max_transition_ms", "observed_transition"),
            Map.entry("scroll_context_preserved", "scroll_state"),
            Map.entry("horizontal_overflow_px", "geometry"),
            Map.entry("min_target_px", "geometry"),
            Map.entry("clipped_elements", "geometry"),
            Map.entry("unintentional_clipped_count", "geometry"),
            Map.entry("obscured_focus_elements", "geometry"),
            Map.entry("fully_obscured_focus_count", "geometry"),
            Map.entry("partially_obscured_focus_count", "geometry"),
            Map.entry("notice_precedes_detail", "geometry"),
            Map.entry("after_focus_role", "input_focus"),
            Map.entry("active_focus", "input_focus"),
            Map.entry("trigger_restored", "input_focus"),
            Map.entry("unexpected_focus_steals", "input_focus"));

    private DriftUiChecks() {}

    private static Object mapOr(Map<?, ?> m, String k, Object def) {
        if (m == null) {
            return def;
        }
        Object v = m.get(k);
        return v != null ? v : def;
    }

    static boolean isElementHidden(Map<?, ?> el) {
        if (el == null) {
            return false;
        }
        String pres = String.valueOf(el.containsKey("presence") ? el.get("presence") : mapOr(el, "state", "")).trim().toLowerCase();
        if ("hidden".equals(pres) || "absent".equals(pres) || "collapsed".equals(pres)) {
            return true;
        }
        if (Boolean.TRUE.equals(el.get("hidden"))
                || Boolean.TRUE.equals(el.get("ariaHidden"))
                || "true".equals(String.valueOf(el.get("aria-hidden")))) {
            return true;
        }
        String disp = String.valueOf(mapOr(el, "display", "")).trim().toLowerCase();
        String vis = String.valueOf(mapOr(el, "visibility", "")).trim().toLowerCase();
        return "none".equals(disp) || "hidden".equals(vis) || "collapse".equals(vis);
    }

    static boolean isElementScrollable(Map<?, ?> el, String axis) {
        if (el == null) {
            return false;
        }
        if (Boolean.TRUE.equals(el.get("scrollable"))) {
            return true;
        }
        if (Boolean.FALSE.equals(el.get("scrollable"))) {
            return false;
        }
        String ox = String.valueOf(mapOr(el, "overflowX", mapOr(el, "overflow", ""))).trim().toLowerCase();
        String oy = String.valueOf(mapOr(el, "overflowY", mapOr(el, "overflow", ""))).trim().toLowerCase();
        boolean sx = "auto".equals(ox) || "scroll".equals(ox) || Boolean.TRUE.equals(el.get("horizontallyScrollable"));
        boolean sy = "auto".equals(oy) || "scroll".equals(oy) || Boolean.TRUE.equals(el.get("verticallyScrollable"));
        return "x".equals(axis) ? sx : ("y".equals(axis) ? sy : (sx || sy));
    }

    static boolean isElementUnintentionallyClipped(Map<?, ?> el) {
        if (el == null || isElementHidden(el)) {
            return false;
        }
        double sw = el.get("scrollWidth") instanceof Number n ? n.doubleValue() : 0.0;
        double cw = el.get("clientWidth") instanceof Number n ? n.doubleValue() : 0.0;
        double sh = el.get("scrollHeight") instanceof Number n ? n.doubleValue() : 0.0;
        double ch = el.get("clientHeight") instanceof Number n ? n.doubleValue() : 0.0;
        return ((sw > cw) && !isElementScrollable(el, "x"))
                || ((sh > ch) && !isElementScrollable(el, "y"));
    }

    static void checkAdapterCapability(
            String contract,
            String id,
            String key,
            Map<String, Object> v,
            Map<String, String> proj) {
        if (!(v.get("adapter") instanceof Map<?, ?> adapter)
                || !(adapter.get("capabilities") instanceof List<?> caps)) {
            return;
        }
        String ptr = proj != null ? proj.getOrDefault(key, "") : "";
        String leaf = "";
        if (ptr != null && !ptr.isEmpty()) {
            String[] segs = ptr.split("/");
            for (int i = segs.length - 1; i >= 0; i--) {
                if (!segs[i].isEmpty()) {
                    leaf = segs[i];
                    break;
                }
            }
        }
        String reqCap = PREDICATE_CAPABILITY.getOrDefault(key, PREDICATE_CAPABILITY.get(leaf));
        if (reqCap != null && !caps.contains(reqCap)) {
            throw new AssertionError(contract + "." + id + ": ui.capability_unverifiable:" + reqCap + " for then." + key);
        }
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
        boolean hasSurfaceEvidence = Boolean.TRUE.equals(v.get("surfaceFound"))
                || Boolean.TRUE.equals(v.get("surface_found"))
                || !rawEls.isEmpty();
        Map<?, ?> presMap = v.get("presentation") instanceof Map<?, ?> pm ? pm : Map.of();

        if ("clipped_elements".equals(key) || "unintentional_clipped_count".equals(key)) {
            Map<?, ?> clipSub = presMap.get("clipping") instanceof Map<?, ?> cm ? cm : Map.of();
            Object expClipObj = v.containsKey(key) ? v.get(key) : clipSub.get("unintentional_clipped_count");
            if (!hasSurfaceEvidence && !(expClipObj instanceof Number)) {
                throw new AssertionError(contract + "." + id + ": unverifiable then." + key + ": empty surface view");
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
            long want = expected instanceof Number n ? n.longValue() : -1L;
            if (clipped != want) {
                throw new AssertionError(contract + "." + id + ": expected " + key + "=" + expected + ", got " + clipped);
            }
            return true;
        }
        if ("horizontal_overflow_px".equals(key)) {
            Object expOvObj = v.containsKey("horizontal_overflow_px")
                    ? v.get("horizontal_overflow_px")
                    : presMap.get("horizontal_overflow_px");
            double vpW = v.get("viewportWidth") instanceof Number n ? n.doubleValue() : 0.0;
            boolean hasVp = vpW > 0.0 || Boolean.TRUE.equals(v.get("surfaceFound")) || Boolean.TRUE.equals(v.get("surface_found"));
            if (!hasVp && !(expOvObj instanceof Number)) {
                throw new AssertionError(contract + "." + id + ": unverifiable then.horizontal_overflow_px: missing viewportWidth");
            }
            double docW = v.get("documentWidth") instanceof Number n ? n.doubleValue() : 0.0;
            double overflow = (expOvObj instanceof Number n && vpW <= 0.0) ? n.doubleValue() : Math.max(0.0, docW - vpW);
            double want = expected instanceof Number n ? n.doubleValue() : -1.0;
            if (overflow > want) {
                throw new AssertionError(contract + "." + id + ": expected horizontal_overflow_px<=" + expected + ", got " + overflow);
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
                    if (Boolean.TRUE.equals(el.get("contrastUnverifiable"))
                            || Boolean.TRUE.equals(el.get("backgroundUnverifiable"))) {
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
                throw new AssertionError(contract + "." + id + ": unverifiable then." + key + ": " + unverifiableCount + " element(s) have indeterminate background");
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
                    throw new AssertionError(contract + "." + id + ": unverifiable then." + key + ": no measured elements");
                }
                minRatio = n.doubleValue();
            }
            if (expected instanceof Map<?, ?> relMap && (relMap.containsKey("min") || relMap.containsKey("max"))) {
                DriftViewChecks.checkRelationalConstraint(c, key, relMap, minRatio, v, thenProj == null ? Map.of() : thenProj);
                return true;
            }
            double want = expected instanceof Number n ? n.doubleValue() : 21.0;
            if (minRatio < want) {
                throw new AssertionError(contract + "." + id + ": expected " + key + ">=" + expected + ", got " + minRatio);
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
                        && !Boolean.TRUE.equals(el.get("spacingException"))) {
                    minPx = Math.min(minPx, Math.min(w.doubleValue(), h.doubleValue()));
                }
            }
            if (Double.isInfinite(minPx)) {
                Map<?, ?> tsSub = presMap.get("target_size") instanceof Map<?, ?> m ? m : Map.of();
                Object expTarget = v.containsKey("min_target_px") ? v.get("min_target_px") : tsSub.get("min_target_size");
                if (!(expTarget instanceof Number n)) {
                    throw new AssertionError(contract + "." + id + ": unverifiable then.min_target_px: no measured elements");
                }
                minPx = n.doubleValue();
            }
            double want = expected instanceof Number n ? n.doubleValue() : 24.0;
            if (minPx < want) {
                throw new AssertionError(contract + "." + id + ": expected min_target_px>=" + expected + ", got " + minPx);
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
                    boolean focusable = !el.containsKey("focusable") || Boolean.TRUE.equals(el.get("focusable"));
                    if (!focusable) {
                        continue;
                    }
                    if (el.get("hitPoints") instanceof List<?> pts && !pts.isEmpty()) {
                        hasFlag = true;
                        long cov = pts.stream().filter(p -> Boolean.TRUE.equals(p)
                                || (p instanceof Map<?, ?> pm && Boolean.TRUE.equals(pm.get("covered")))).count();
                        if (checkPartial ? cov > 0 : cov == pts.size()) {
                            obscured++;
                        }
                    } else if (el.containsKey("fullyObscured") || el.containsKey("partiallyObscured")
                            || el.containsKey("obscured") || el.containsKey("focusObscured")) {
                        hasFlag = true;
                        boolean full = Boolean.TRUE.equals(el.get("fullyObscured"))
                                || Boolean.TRUE.equals(el.get("obscured"))
                                || Boolean.TRUE.equals(el.get("focusObscured"));
                        boolean part = Boolean.TRUE.equals(el.get("partiallyObscured")) || full;
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
            if (!hasFlag && !hasSurfaceEvidence && !(expFocus instanceof Number)) {
                throw new AssertionError(contract + "." + id + ": unverifiable then." + key + ": no measured elements");
            }
            if (!hasFlag && expFocus instanceof Number n) {
                obscured = n.longValue();
            }
            long want = expected instanceof Number n ? n.longValue() : -1L;
            if (obscured != want) {
                throw new AssertionError(contract + "." + id + ": expected " + key + "=" + expected + ", got " + obscured);
            }
            return true;
        }
        if ("unverified_elements".equals(key) || "unverifiable_checks".equals(key)) {
            Map<?, ?> evSub = v.get("evidence") instanceof Map<?, ?> m ? m : Map.of();
            Object rawU = v.containsKey("unverified_elements")
                    ? v.get("unverified_elements")
                    : (v.containsKey("unverifiable_checks")
                            ? v.get("unverifiable_checks")
                            : mapOr(evSub, "unverifiable_checks", 0L));
            long actU = rawU instanceof Number n ? n.longValue() : 0L;
            long want = expected instanceof Number n ? n.longValue() : -1L;
            if (actU != want) {
                throw new AssertionError(contract + "." + id + ": expected " + key + "=" + expected + ", got " + actU);
            }
            return true;
        }
        return false;
    }
}
