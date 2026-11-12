// Zero-dependency C# (.NET 8+ / Unity / Godot .NET) forward verification bridge for DRIFT.
// Conforms to drift.bridge-capabilities/1.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace Drift
{
    public static class DriftBridge
    {
        public const string VERSION = "drift.csharp@0.6.0";
        public const string BRIDGE_RUNTIME_BASELINE = "dotnet-8.0";

        public static readonly IReadOnlyList<string> CAPABILITIES = new[]
        {
            "predicates",
            "forbid_keys",
            "not_in",
            "tuning_invariants",
            "case_frames",
            "counterexample_replay",
            "sim_receipt",
        };

        public static Dictionary<string, object> BridgeCapabilities()
        {
            return new Dictionary<string, object>
            {
                ["schema"] = "drift.bridge-capabilities/1",
                ["bridge"] = "drift.csharp",
                ["version"] = VERSION,
                ["runtime_baseline"] = BRIDGE_RUNTIME_BASELINE,
                ["capabilities"] = CAPABILITIES,
            };
        }

        public static void RequireCapabilities(IEnumerable<string> required)
        {
            foreach (var cap in required)
            {
                if (!CAPABILITIES.Contains(cap))
                {
                    throw new InvalidOperationException("bridge.capability_unsupported:" + cap);
                }
            }
        }

        public static void CheckMonotonic(string key, IReadOnlyList<double> seq, string mode)
        {
            if (seq == null || seq.Count == 0)
            {
                throw new InvalidOperationException($"then.{key}: empty numeric sequence for monotonic");
            }
            for (int i = 1; i < seq.Count; i++)
            {
                double prev = seq[i - 1];
                double cur = seq[i];
                bool ok = mode switch
                {
                    "non_decreasing" => prev - 1e-9 <= cur,
                    "strictly_increasing" => prev + 1e-9 < cur,
                    "non_increasing" => prev + 1e-9 >= cur,
                    "strictly_decreasing" => prev - 1e-9 > cur,
                    _ => false,
                };
                if (!ok)
                {
                    throw new InvalidOperationException($"then.{key}: monotonic {mode} violated at index {i}");
                }
            }
        }

        public static void CheckStepMaxDelta(string key, IReadOnlyList<double> seq, double maxDelta)
        {
            if (seq == null || seq.Count == 0 || maxDelta <= 0.0)
            {
                throw new InvalidOperationException($"then.{key}: invalid sequence or step_max_delta");
            }
            for (int i = 1; i < seq.Count; i++)
            {
                if (Math.Abs(seq[i] - seq[i - 1]) > maxDelta + 1e-9)
                {
                    throw new InvalidOperationException($"then.{key}: step_max_delta exceeded at index {i}");
                }
            }
        }

        public static void CheckSumTotal(string key, IReadOnlyList<double> seq, double minSum, double maxSum)
        {
            if (seq == null || seq.Count == 0)
            {
                throw new InvalidOperationException($"then.{key}: empty sequence for sum_total");
            }
            double total = seq.Sum();
            if (total + 1e-9 < minSum || total - 1e-9 > maxSum)
            {
                throw new InvalidOperationException($"then.{key}: sum_total {total} outside [{minSum}, {maxSum}]");
            }
        }

        public static void CheckApprox(string key, double actual, double target, double absTol, double relTol = 0.0)
        {
            if (absTol < 0.0 || relTol < 0.0 || Math.Abs(actual - target) > absTol + relTol * Math.Abs(target))
            {
                throw new InvalidOperationException($"then.{key}: {actual} outside approx {target}");
            }
        }

        public static void CheckFrame(
            IReadOnlyList<string> scopeWrites,
            IReadOnlyList<string> allowedCaseWrites,
            IReadOnlyDictionary<string, int> observedWrites,
            IList<string> readKeys)
        {
            var allowed = new HashSet<string>(allowedCaseWrites);
            foreach (var kv in observedWrites)
            {
                if (kv.Value < 0)
                {
                    throw new InvalidOperationException($"frame.invalid:{kv.Key}: writes must be non-negative");
                }
                if (!allowed.Contains(kv.Key) && kv.Value != 0)
                {
                    throw new InvalidOperationException($"undeclared write on perimeter resource \"{kv.Key}\": expected 0 writes, observed {kv.Value}");
                }
            }
            foreach (var res in scopeWrites)
            {
                if (!allowed.Contains(res))
                {
                    if (observedWrites.TryGetValue(res, out int wCount))
                    {
                        if (wCount < 0 || wCount != 0)
                        {
                            throw new InvalidOperationException($"frame.violation:{res}");
                        }
                        readKeys.Add("@frame:" + res);
                    }
                }
                else
                {
                    readKeys.Add("@frame:" + res);
                }
            }
        }

        public static void CheckPrefix(string key, string actual, string prefix)
        {
            if (actual == null || prefix == null || !actual.StartsWith(prefix, StringComparison.Ordinal))
            {
                throw new InvalidOperationException($"then.{key}: expected prefix \"{prefix}\", got \"{actual}\"");
            }
        }

        public static void CheckSuffix(string key, string actual, string suffix)
        {
            if (actual == null || suffix == null || !actual.EndsWith(suffix, StringComparison.Ordinal))
            {
                throw new InvalidOperationException($"then.{key}: expected suffix \"{suffix}\", got \"{actual}\"");
            }
        }

        public static void CheckContains(string key, string actual, string needle)
        {
            if (actual == null || needle == null || !actual.Contains(needle, StringComparison.Ordinal))
            {
                throw new InvalidOperationException($"then.{key}: expected \"{actual}\" to contain \"{needle}\"");
            }
        }

        public static void CheckNonEmpty(string key, string actual, bool wantNonEmpty)
        {
            bool empty = string.IsNullOrEmpty(actual);
            if (wantNonEmpty ? empty : !empty)
            {
                throw new InvalidOperationException($"then.{key}: non_empty violation");
            }
        }

        public static bool HasKeyRecursive(object val, string fk, bool isRoot = true)
        {
            if (val is IReadOnlyDictionary<string, object> roDict)
            {
                if (roDict.ContainsKey(fk)) return true;
                foreach (var kv in roDict)
                {
                    if (isRoot && kv.Key == "_frame" && fk != "_frame") continue;
                    if (HasKeyRecursive(kv.Value, fk, false)) return true;
                }
                return false;
            }
            if (val is IDictionary<string, object> dict)
            {
                if (dict.ContainsKey(fk)) return true;
                foreach (var kv in dict)
                {
                    if (isRoot && kv.Key == "_frame" && fk != "_frame") continue;
                    if (HasKeyRecursive(kv.Value, fk, false)) return true;
                }
                return false;
            }
            if (val is System.Collections.IEnumerable seq && !(val is string))
            {
                foreach (var item in seq)
                {
                    if (HasKeyRecursive(item, fk, false)) return true;
                }
            }
            return false;
        }

        public static void CheckForbidKeys(string key, IReadOnlyDictionary<string, object> obj, IEnumerable<string> forbidKeys)
        {
            if (obj == null)
            {
                throw new InvalidOperationException($"then.{key}: expected object for forbid_keys");
            }
            foreach (var fk in forbidKeys)
            {
                if (HasKeyRecursive(obj, fk, true))
                {
                    throw new InvalidOperationException($"then.{key}: forbidden key \"{fk}\" present");
                }
            }
        }

        public static void CheckNotIn(string key, object actual, IEnumerable<object> forbidden)
        {
            if (actual == null)
            {
                throw new InvalidOperationException($"then.{key}: expected non-null value for not_in");
            }
            if (forbidden.Any(f => Equals(actual, f)))
            {
                throw new InvalidOperationException($"then.{key}: forbidden value \"{actual}\" in not_in");
            }
        }

        public static int ReplayCounterexamples(
            string contractId,
            string caseId,
            IEnumerable<Dictionary<string, object>> fixtures,
            Action<Dictionary<string, object>> runner)
        {
            int count = 0;
            foreach (var fx in fixtures)
            {
                if (Convert.ToString(fx.GetValueOrDefault("contract")) != contractId
                    || (fx.ContainsKey("case") && Convert.ToString(fx.GetValueOrDefault("case")) != caseId))
                {
                    continue;
                }
                var witness = fx.GetValueOrDefault("witness") as Dictionary<string, object>;
                var whenInput = (witness?.GetValueOrDefault("when") as Dictionary<string, object>) ?? fx;
                runner(whenInput);
                count++;
            }
            return count;
        }
        public static void CheckPlanBalance(string key, double actual, IEnumerable<double> adds, IEnumerable<double> subs, double absTol = 1e-9)
        {
            double total = (adds?.Sum() ?? 0.0) - (subs?.Sum() ?? 0.0);
            if (absTol < 0.0 || Math.Abs(actual - total) > absTol)
            {
                throw new InvalidOperationException($"then.{key}: balance {actual} != {total}");
            }
        }

        public static void CheckPlanScaledBounds(string key, double actual, double conv, double? minVal, double? maxVal)
        {
            if (minVal.HasValue && actual + 1e-9 < minVal.Value * conv)
                throw new InvalidOperationException($"then.{key}: {actual} < scaled min {minVal.Value * conv}");
            if (maxVal.HasValue && actual - 1e-9 > maxVal.Value * conv)
                throw new InvalidOperationException($"then.{key}: {actual} > scaled max {maxVal.Value * conv}");
        }
    }
}
