#ifndef DRIFT_CPP_HPP
#define DRIFT_CPP_HPP

// Zero-dependency C++20 forward verification bridge for DRIFT (Unreal Engine / native C++).
// Conforms to drift.bridge-capabilities/1.

#include <cmath>
#include <fstream>
#include <functional>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace drift {

inline constexpr const char* VERSION = "drift.cpp@0.5.1";
inline constexpr const char* BRIDGE_RUNTIME_BASELINE = "cpp-20";

inline const std::vector<std::string>& capabilities() {
    static const std::vector<std::string> caps = {
        "predicates",
        "forbid_keys",
        "not_in",
        "tuning_invariants",
        "case_frames",
        "counterexample_replay",
        "sim_receipt",
    };
    return caps;
}

inline std::string bridgeCapabilitiesJson() {
    return R"({"schema":"drift.bridge-capabilities/1","bridge":"drift.cpp","version":"drift.cpp@0.5.1","runtime_baseline":"cpp-20","capabilities":["predicates","forbid_keys","not_in","tuning_invariants","case_frames","counterexample_replay","sim_receipt"]})";
}

inline void requireCapabilities(const std::vector<std::string>& required) {
    const auto& allowed = capabilities();
    for (const auto& cap : required) {
        bool found = false;
        for (const auto& c : allowed) {
            if (c == cap) {
                found = true;
                break;
            }
        }
        if (!found) {
            throw std::runtime_error("bridge.capability_unsupported:" + cap);
        }
    }
}

inline void checkMonotonic(const std::string& key, const std::vector<double>& seq, const std::string& mode) {
    if (seq.empty()) {
        throw std::runtime_error("then." + key + ": empty numeric sequence for monotonic");
    }
    for (std::size_t i = 1; i < seq.size(); ++i) {
        double prev = seq[i - 1];
        double cur = seq[i];
        bool ok = false;
        if (mode == "non_decreasing") ok = (prev - 1e-9 <= cur);
        else if (mode == "strictly_increasing") ok = (prev + 1e-9 < cur);
        else if (mode == "non_increasing") ok = (prev + 1e-9 >= cur);
        else if (mode == "strictly_decreasing") ok = (prev - 1e-9 > cur);
        if (!ok) {
            throw std::runtime_error("then." + key + ": monotonic " + mode + " violated at index " + std::to_string(i));
        }
    }
}

inline void checkStepMaxDelta(const std::string& key, const std::vector<double>& seq, double maxDelta) {
    if (seq.empty() || maxDelta <= 0.0) {
        throw std::runtime_error("then." + key + ": invalid sequence or step_max_delta");
    }
    for (std::size_t i = 1; i < seq.size(); ++i) {
        if (std::fabs(seq[i] - seq[i - 1]) > maxDelta + 1e-9) {
            throw std::runtime_error("then." + key + ": step_max_delta exceeded at index " + std::to_string(i));
        }
    }
}

inline void checkSumTotal(const std::string& key, const std::vector<double>& seq, double minSum, double maxSum) {
    if (seq.empty()) {
        throw std::runtime_error("then." + key + ": empty sequence for sum_total");
    }
    double total = 0.0;
    for (double v : seq) {
        total += v;
    }
    if (total + 1e-9 < minSum || total - 1e-9 > maxSum) {
        throw std::runtime_error("then." + key + ": sum_total " + std::to_string(total) + " outside bounds");
    }
}

inline void checkApprox(const std::string& key, double actual, double target, double absTol, double relTol = 0.0) {
    if (absTol < 0.0 || relTol < 0.0) {
        throw std::runtime_error("then." + key + ": negative approx tolerance");
    }
    double rad = absTol + relTol * std::fabs(target);
    if (std::fabs(actual - target) > rad) {
        throw std::runtime_error("then." + key + ": " + std::to_string(actual) + " outside approx " + std::to_string(target));
    }
}

inline void checkForbidKeys(const std::string& key, const std::map<std::string, std::string>& obj, const std::vector<std::string>& forbidKeys) {
    for (const auto& fk : forbidKeys) {
        if (obj.find(fk) != obj.end()) {
            throw std::runtime_error("then." + key + ": forbidden key \"" + fk + "\" present");
        }
    }
}

inline void checkForbidKeysNested(
    const std::string& key,
    const std::map<std::string, std::map<std::string, std::string>>& nestedObj,
    const std::vector<std::string>& forbidKeys) {
    for (const auto& fk : forbidKeys) {
        if (nestedObj.find(fk) != nestedObj.end()) {
            throw std::runtime_error("then." + key + ": forbidden key \"" + fk + "\" present");
        }
        for (const auto& kv : nestedObj) {
            if (kv.first == "_frame" && fk != "_frame") continue;
            if (kv.second.find(fk) != kv.second.end()) {
                throw std::runtime_error("then." + key + ": forbidden key \"" + fk + "\" present");
            }
        }
    }
}

inline void checkNotIn(const std::string& key, const std::string& actual, const std::vector<std::string>& forbidden) {
    for (const auto& fv : forbidden) {
        if (actual == fv) {
            throw std::runtime_error("then." + key + ": forbidden value \"" + actual + "\" in not_in");
        }
    }
}

inline void checkPrefix(const std::string& key, const std::string& actual, const std::string& prefix) {
    if (actual.rfind(prefix, 0) != 0) {
        throw std::runtime_error("then." + key + ": expected prefix \"" + prefix + "\", got \"" + actual + "\"");
    }
}

inline void checkSuffix(const std::string& key, const std::string& actual, const std::string& suffix) {
    if (actual.size() < suffix.size() || actual.compare(actual.size() - suffix.size(), suffix.size(), suffix) != 0) {
        throw std::runtime_error("then." + key + ": expected suffix \"" + suffix + "\", got \"" + actual + "\"");
    }
}

inline void checkContains(const std::string& key, const std::string& actual, const std::string& needle) {
    if (actual.find(needle) == std::string::npos) {
        throw std::runtime_error("then." + key + ": expected \"" + actual + "\" to contain \"" + needle + "\"");
    }
}

inline void checkNonEmpty(const std::string& key, const std::string& actual, bool wantNonEmpty) {
    if (wantNonEmpty ? actual.empty() : !actual.empty()) {
        throw std::runtime_error("then." + key + ": non_empty violation");
    }
}

inline std::string jsonStrArray(const std::vector<std::string>& items) {
    std::ostringstream oss;
    oss << "[";
    for (std::size_t i = 0; i < items.size(); ++i) {
        if (i > 0) oss << ",";
        oss << "\"" << items[i] << "\"";
    }
    oss << "]";
    return oss.str();
}

inline void checkFrame(
    const std::vector<std::string>& scopeWrites,
    const std::vector<std::string>& allowedCaseWrites,
    const std::map<std::string, int>& observedWrites,
    std::vector<std::string>& readOut) {
    std::set<std::string> allowed(allowedCaseWrites.begin(), allowedCaseWrites.end());
    for (const auto& kv : observedWrites) {
        if (kv.second < 0) {
            throw std::runtime_error("frame.invalid:" + kv.first + ": writes must be non-negative");
        }
        if (allowed.find(kv.first) == allowed.end() && kv.second != 0) {
            throw std::runtime_error("undeclared write on perimeter resource \"" + kv.first + "\": expected 0 writes, observed " + std::to_string(kv.second));
        }
    }
    for (const auto& res : scopeWrites) {
        if (allowed.find(res) == allowed.end()) {
            auto it = observedWrites.find(res);
            if (it != observedWrites.end()) {
                if (it->second < 0 || it->second != 0) {
                    throw std::runtime_error("frame.violation:" + res);
                }
                readOut.push_back("@frame:" + res);
            }
        } else {
            readOut.push_back("@frame:" + res);
        }
    }
}

inline void emitProofShard(
    const std::string& eventsPath,
    const std::string& metaPath,
    const std::string& contractId,
    const std::string& digest,
    const std::string& testId,
    const std::string& caseId,
    bool verified,
    const std::string& inputFile,
    const std::string& inputHash) {
    {
        const bool is03 = digest.rfind("dr2b:", 0) == 0;
        std::ofstream ef(eventsPath, std::ios::trunc);
        ef << (is03 ? "{\"capabilities\":[\"rel-keys-guard/1\",\"rel-series/1\",\"rel-tol/1\"],\"cases\":[\"" : "{\"cases\":[\"")
           << caseId << "\"],\"contract\":\"" << contractId
           << "\",\"digest\":\"" << digest << "\",\"level\":\"unit\",\"outcome\":\"passed\",\"read\":["
           << (verified ? ("\"" + caseId + "\"") : "") << "]"
           << (is03 ? ",\"schema\":\"0.3\"" : "")
           << ",\"test\":\"" << testId << "\"}\n";
    }
    std::string cls = testId.substr(0, testId.find('#'));
    {
        std::ofstream mf(metaPath, std::ios::trunc);
        mf << "{\"classes\":[\"" << cls << "\"],\"inputs\":{\"" << testId << "\":{\""
           << inputFile << "\":\"" << inputHash << "\"}},\"tests\":[\"" << testId << "\"],\"version\":1}\n";
    }
}

inline void emitSimReceipt(
    const std::string& simPath,
    const std::string& contractId,
    const std::string& digest,
    const std::string& simId,
    const std::string& runnerRef,
    const std::string& subjectRef,
    const std::string& snapshot,
    const std::vector<std::string>& coveredScope,
    const std::vector<std::string>& cases,
    const std::string& seedRef,
    const std::string& inputRef,
    const std::string& trajRef,
    int ticksExecuted,
    const std::vector<std::string>& platformsCompared,
    int windowsTested,
    int maxRollbackFrames,
    int resimMismatches,
    int leakedAmbientMutations,
    const std::vector<std::string>& activeSaveEpochs,
    const std::vector<std::string>& compatibleEpochs,
    const std::vector<std::string>& incompatibleEpochs,
    const std::vector<std::string>& invariantsChecked) {
    const char* outcome = (resimMismatches > 0 || leakedAmbientMutations > 0 || !incompatibleEpochs.empty())
        ? "violated"
        : ((ticksExecuted <= 0 || windowsTested <= 0 || maxRollbackFrames <= 0 || platformsCompared.empty() || activeSaveEpochs.empty())
            ? "inconclusive"
            : "passed");
    std::ofstream sf(simPath, std::ios::trunc);
    sf << "{\"cases\":" << jsonStrArray(cases) << ",\"code_snapshot\":\"" << snapshot
       << "\",\"contract\":\"" << contractId << "\",\"covered_scope\":" << jsonStrArray(coveredScope)
       << ",\"digest\":\"" << digest << "\",\"outcome\":\"" << outcome
       << "\",\"rollback_invariance\":{\"leaked_ambient_mutations\":" << leakedAmbientMutations
       << ",\"max_rollback_frames\":" << maxRollbackFrames << ",\"resim_mismatches\":" << resimMismatches
       << ",\"windows_tested\":" << windowsTested << "},\"runner\":\"drift-cpp-sim\",\"runner_ref\":\"" << runnerRef
       << "\",\"save_epoch_compatibility\":{\"active_save_epochs\":" << jsonStrArray(activeSaveEpochs)
       << ",\"compatible_epochs\":" << jsonStrArray(compatibleEpochs)
       << ",\"incompatible_epochs\":" << jsonStrArray(incompatibleEpochs)
       << ",\"invariants_checked\":" << jsonStrArray(invariantsChecked)
       << "},\"schema\":\"drift.sim-receipt/1\",\"simulation_id\":\"" << simId
       << "\",\"subject_ref\":\"" << subjectRef << "\",\"tick_determinism\":{\"divergent_ticks\":[],\"input_stream_ref\":\""
       << inputRef << "\",\"platforms_compared\":" << jsonStrArray(platformsCompared) << ",\"seed_corpus_ref\":\""
       << seedRef << "\",\"ticks_executed\":" << ticksExecuted << ",\"trajectory_digest\":\"" << trajRef << "\"}}\n";
}

} // namespace drift

#endif // DRIFT_CPP_HPP
