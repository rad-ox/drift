<?php
declare(strict_types=1);

namespace Drift;

use RuntimeException;

/**
 * Zero-dependency PHP 8.2+ forward verification bridge for DRIFT.
 * Consumes precompiled drift.bridge-plan/1 plans and conforms to drift.bridge-capabilities/1.
 */
final class Drift
{
    public const VERSION = 'drift.php@0.7.0';
    public const BRIDGE_RUNTIME_BASELINE = 'php-8.2-cli';
    public const CAPABILITIES = ['predicates', 'projections', 'forbid_keys', 'not_in', 'case_frames', 'counterexample_replay', 'in_process_mutants'];
    public const SUPPORTED_REL_KEYS = ['eq', 'in', 'not_in', 'min', 'max', 'len', 'min_len', 'max_len', 'non_empty', 'prefix', 'suffix', 'contains', 'forbid_keys', 'allowed_keys', 'le_field', 'ge_field', 'eq_field', 'sum_fields', 'monotonic', 'step_max_delta', 'sum_total', 'approx', 'abs_tol', 'rel_tol', 'balance_fields', 'unit', 'unit_conversion'];

    public static function bridgeCapabilities(): array
    {
        return ['schema' => 'drift.bridge-capabilities/1', 'bridge' => 'drift.php', 'version' => self::VERSION, 'runtime_baseline' => self::BRIDGE_RUNTIME_BASELINE, 'capabilities' => self::CAPABILITIES];
    }

    public static function requireCapabilities(array $required): void
    {
        foreach ($required as $cap) {
            if (!in_array((string)$cap, self::CAPABILITIES, true)) throw new RuntimeException('bridge.capability_unsupported:' . (string)$cap);
        }
    }

    public static function resolvePointer(array $doc, string $pointer): array
    {
        if ($pointer === '' || $pointer === '/') return [true, $doc];
        if ($pointer[0] !== '/') return [array_key_exists($pointer, $doc), $doc[$pointer] ?? null];
        $cur = $doc;
        foreach (explode('/', substr($pointer, 1)) as $rawSeg) {
            $seg = str_replace(['~1', '~0'], ['/', '~'], $rawSeg);
            if (!is_array($cur) || !array_key_exists($seg, $cur)) return [false, null];
            $cur = $cur[$seg];
        }
        return [true, $cur];
    }

    private static function isFiniteNum(mixed $v): bool
    {
        return (is_int($v) || is_float($v)) && !is_nan((float)$v) && !is_infinite((float)$v);
    }

    private static function valuesEqual(mixed $a, mixed $b): bool
    {
        if (is_bool($a) || is_bool($b)) return is_bool($a) && is_bool($b) && $a === $b;
        if (self::isFiniteNum($a) || self::isFiniteNum($b)) return self::isFiniteNum($a) && self::isFiniteNum($b) && abs((float)$a - (float)$b) <= 1e-9;
        if ($a === null || $b === null) return $a === null && $b === null;
        if (is_array($a) && is_array($b)) {
            if (count($a) !== count($b)) return false;
            if (array_is_list($a) && array_is_list($b)) {
                foreach ($a as $i => $av) if (!self::valuesEqual($av, $b[$i])) return false;
                return true;
            }
            foreach ($a as $k => $av) if (!array_key_exists($k, $b) || !self::valuesEqual($av, $b[$k])) return false;
            return true;
        }
        return $a === $b;
    }

    private static function hasKeyRecursive(mixed $val, string $fk, bool $isRoot = true): bool
    {
        if (!is_array($val)) return false;
        if (array_is_list($val)) {
            foreach ($val as $item) if (self::hasKeyRecursive($item, $fk, false)) return true;
            return false;
        }
        if (array_key_exists($fk, $val)) return true;
        foreach ($val as $k => $v) {
            if (!($isRoot && (string)$k === '_frame' && $fk !== '_frame' && is_array($v)) && self::hasKeyRecursive($v, $fk, false)) return true;
        }
        return false;
    }

    public static function checkValue(string $key, mixed $actual, mixed $expected, bool $actualPresent = true, array $observed = [], array $projThen = [], array $whenEnv = []): void
    {
        if (is_float($actual) && (is_nan($actual) || is_infinite($actual))) throw new RuntimeException("then.{$key}: non-finite float");
        if (!is_array($expected) || array_is_list($expected)) {
            if (!$actualPresent || !self::valuesEqual($actual, $expected)) throw new RuntimeException("then.{$key}: mismatch");
            return;
        }
        if (!$expected) throw new RuntimeException("then.{$key}: empty predicate");
        foreach (array_keys($expected) as $op) if (!in_array((string)$op, self::SUPPORTED_REL_KEYS, true)) throw new RuntimeException("then.{$key}: unsupported operator {$op}");
        $len = is_string($actual) ? (function_exists('mb_strlen') ? mb_strlen($actual, 'UTF-8') : preg_match_all('/./us', $actual)) : (is_array($actual) ? count($actual) : -1);
        if (array_key_exists('eq', $expected) && (!$actualPresent || !self::valuesEqual($actual, $expected['eq']))) throw new RuntimeException("then.{$key}: eq violation");
        $series = array_key_exists('monotonic', $expected) || array_key_exists('sum_total', $expected) || array_key_exists('step_max_delta', $expected);
        if (array_key_exists('in', $expected)) {
            $okIn = is_array($expected['in']) && $actualPresent && array_reduce($expected['in'], fn($acc, $c) => $acc || self::valuesEqual($actual, $c), false);
            if (!$okIn) throw new RuntimeException("then.{$key}: not in allowed set");
        }
        if (array_key_exists('not_in', $expected)) {
            if (!$actualPresent || $actual === null) throw new RuntimeException("then.{$key}: null in not_in");
            if (is_array($expected['not_in'])) {
                foreach ($expected['not_in'] as $forb) if (self::valuesEqual($actual, $forb)) throw new RuntimeException("then.{$key}: forbidden by not_in");
            } elseif (!self::valuesEqual($actual, $expected['not_in'])) throw new RuntimeException("then.{$key}: mutant killed");
        }
        if (array_key_exists('approx', $expected)) {
            $at = array_key_exists('abs_tol', $expected) && self::isFiniteNum($expected['abs_tol']) ? (float)$expected['abs_tol'] : 0.0;
            $rt = array_key_exists('rel_tol', $expected) && self::isFiniteNum($expected['rel_tol']) ? (float)$expected['rel_tol'] : 0.0;
            if (!self::isFiniteNum($actual) || !self::isFiniteNum($expected['approx']) || (!array_key_exists('abs_tol', $expected) && !array_key_exists('rel_tol', $expected)) || $at < 0.0 || $rt < 0.0) throw new RuntimeException("then.{$key}: invalid approx");
            $ap = (float)$expected['approx'];
            if (abs((float)$actual - $ap) > $at + $rt * abs($ap)) throw new RuntimeException("then.{$key}: outside approx");
        }
        if (!$series && array_key_exists('min', $expected) && (!self::isFiniteNum($actual) || !self::isFiniteNum($expected['min']) || (float)$actual + 1e-9 < (float)$expected['min'])) throw new RuntimeException("then.{$key}: < min");
        if (!$series && array_key_exists('max', $expected) && (!self::isFiniteNum($actual) || !self::isFiniteNum($expected['max']) || (float)$actual - 1e-9 > (float)$expected['max'])) throw new RuntimeException("then.{$key}: > max");
        if (array_key_exists('len', $expected) && (!is_int($expected['len']) || $expected['len'] < 0 || $len !== $expected['len'])) throw new RuntimeException("then.{$key}: len mismatch");
        if (array_key_exists('min_len', $expected) && (!is_int($expected['min_len']) || $expected['min_len'] < 0 || $len < 0 || $len < $expected['min_len'])) throw new RuntimeException("then.{$key}: < min_len");
        if (array_key_exists('max_len', $expected) && (!is_int($expected['max_len']) || $expected['max_len'] < 0 || $len < 0 || $len > $expected['max_len'])) throw new RuntimeException("then.{$key}: > max_len");
        if (array_key_exists('non_empty', $expected) && (!is_bool($expected['non_empty']) || $len < 0 || ($expected['non_empty'] ? $len <= 0 : $len !== 0))) throw new RuntimeException("then.{$key}: non_empty violation");
        if (array_key_exists('prefix', $expected) && (!is_string($expected['prefix']) || !is_string($actual) || !str_starts_with($actual, $expected['prefix']))) throw new RuntimeException("then.{$key}: prefix violation");
        if (array_key_exists('suffix', $expected) && (!is_string($expected['suffix']) || !is_string($actual) || !str_ends_with($actual, $expected['suffix']))) throw new RuntimeException("then.{$key}: suffix violation");
        if (array_key_exists('contains', $expected)) {
            $ce = $expected['contains'];
            $reqs = is_array($ce) && array_is_list($ce) ? $ce : [$ce];
            $ok = is_string($actual) ? (is_string($ce) ? str_contains($actual, $ce) : (is_array($ce) && array_is_list($ce) && array_reduce($ce, fn($a, $s) => $a && is_string($s) && str_contains($actual, $s), true)))
                : (is_array($actual) && array_is_list($actual) && array_reduce($reqs, fn($a, $r) => $a && array_reduce($actual, fn($f, $it) => $f || self::valuesEqual($it, $r), false), true));
            if (!$ok) throw new RuntimeException("then.{$key}: contains violation");
        }
        if (array_key_exists('forbid_keys', $expected)) {
            if (!is_array($actual) || (array_is_list($actual) && !empty($actual))) throw new RuntimeException("then.{$key}: expected object");
            $isRoot = ($actual === $observed);
            if (is_array($expected['forbid_keys'])) {
                foreach ($expected['forbid_keys'] as $fk) if (self::hasKeyRecursive($actual, (string)$fk, $isRoot)) throw new RuntimeException("then.{$key}: forbidden key {$fk}");
            } elseif (!is_string($expected['forbid_keys']) || !self::hasKeyRecursive($actual, $expected['forbid_keys'], $isRoot)) throw new RuntimeException("then.{$key}: forbid_keys violation");
        }
        if (array_key_exists('allowed_keys', $expected)) {
            if (!is_array($actual) || !is_array($expected['allowed_keys'])) throw new RuntimeException("then.{$key}: expected object");
            foreach (array_keys($actual) as $ak) {
                if (!((string)$ak === '_frame' && is_array($actual[$ak])) && !in_array((string)$ak, $expected['allowed_keys'], true)) throw new RuntimeException("then.{$key}: key {$ak} not allowed");
            }
        }
        $tol = $expected['abs_tol'] ?? 1e-9;
        foreach (['le_field', 'ge_field', 'eq_field'] as $op) {
            if (!array_key_exists($op, $expected)) continue;
            [$found, $peer] = self::resolvePeer($observed, $projThen, $expected[$op], $whenEnv);
            $ok = $found && ($op === 'eq_field' ? self::valuesEqual($actual, $peer) : (self::isFiniteNum($actual) && self::isFiniteNum($peer) && ($op === 'le_field' ? $actual - $tol <= $peer : $actual + $tol >= $peer)));
            if (!$ok) throw new RuntimeException("then.{$key}: {$op} violation");
        }
        foreach (['sum_fields', 'balance_fields'] as $op) {
            if (!array_key_exists($op, $expected)) continue;
            $expr = $expected[$op];
            if (!is_array($expr) || !self::isFiniteNum($actual) || ($op === 'sum_fields' && count($expr) < 2)) throw new RuntimeException("then.{$key}: invalid {$op}");
            $sides = $op === 'sum_fields' ? ['add' => $expr] : $expr;
            $total = 0.0;
            foreach (['add' => 1, 'sub' => -1] as $side => $sign) {
                foreach (($sides[$side] ?? []) as $ref) {
                    [$found, $peer] = self::resolvePeer($observed, $projThen, $ref, $whenEnv);
                    if (!$found || !self::isFiniteNum($peer)) throw new RuntimeException("then.{$key}: missing peer {$ref}");
                    $total += $sign * $peer;
                }
            }
            if (!is_finite($total) || abs($actual - $total) > $tol) throw new RuntimeException("then.{$key}: {$op} violation");
        }
        if ($series) {
            if (!is_array($actual) || !$actual || ((array_key_exists('monotonic', $expected) || array_key_exists('step_max_delta', $expected)) && !array_is_list($actual))) throw new RuntimeException("then.{$key}: bad sequence");
            $vals = array_values($actual);
            foreach ($vals as $i => $v) {
                if (!self::isFiniteNum($v) || (array_key_exists('min', $expected) && $v + $tol < $expected['min']) || (array_key_exists('max', $expected) && $v - $tol > $expected['max'])) throw new RuntimeException("then.{$key}: sequence bounds");
                if ($i === 0) continue;
                $prev = $vals[$i - 1];
                if (array_key_exists('monotonic', $expected) && !match ($expected['monotonic']) { 'non_decreasing' => $prev - $tol <= $v, 'non_increasing' => $prev + $tol >= $v, 'strictly_increasing' => $prev + $tol < $v, 'strictly_decreasing' => $prev - $tol > $v, default => false }) throw new RuntimeException("then.{$key}: monotonic violation");
                if (array_key_exists('step_max_delta', $expected) && (!self::isFiniteNum($expected['step_max_delta']) || $expected['step_max_delta'] <= 0 || abs($v - $prev) > $expected['step_max_delta'] + $tol)) throw new RuntimeException("then.{$key}: step_max_delta violation");
            }
            if (array_key_exists('sum_total', $expected)) {
                $tot = array_sum($vals);
                $b = is_array($expected['sum_total']) ? $expected['sum_total'] : ['eq' => $expected['sum_total']];
                if (!is_finite((float)$tot) || !$b) throw new RuntimeException("then.{$key}: invalid sum_total");
                foreach ($b as $op => $bnd) if (!self::isFiniteNum($bnd) || !match ($op) { 'eq' => abs($tot - $bnd) <= $tol, 'min' => $tot + $tol >= $bnd, 'max' => $tot - $tol <= $bnd, default => false }) throw new RuntimeException("then.{$key}: sum_total violation");
            }
        }
    }

    private static function resolvePeer(array $observed, array $projThen, mixed $ref, array $whenEnv): array
    {
        if (!is_string($ref) || $ref === '') return [false, null];
        if (str_starts_with($ref, 'when.')) {
            if (array_key_exists($ref, $observed)) return [true, $observed[$ref]];
            $inputs = array_replace($whenEnv, $observed['_when_env'] ?? [], $observed['before'] ?? [], $observed['when'] ?? []);
            $k = substr($ref, 5);
            return [array_key_exists($k, $inputs), $inputs[$k] ?? null];
        }
        if (str_starts_with($ref, 'then.')) $ref = substr($ref, 5);
        return self::resolvePointer($observed, $projThen[$ref] ?? (str_starts_with($ref, '/') ? $ref : '/' . str_replace(['~', '/'], ['~0', '~1'], $ref)));
    }

    private static function verifySinglePhpFrame(string $res, mixed $obs, bool $isAmbient): void
    {
        $checked = false;
        $lbl = $isAmbient ? "undeclared write on perimeter resource \"{$res}\"" : "frame.violation:{$res}";
        if (is_int($obs) && $obs >= 0) {
            if ($obs > 0) throw new RuntimeException("{$lbl}: expected 0 writes, observed {$obs}");
            return;
        }
        if (is_array($obs) && !array_is_list($obs)) {
            foreach (['writes', 'operations', 'events'] as $wk) {
                if (!array_key_exists($wk, $obs)) continue;
                $wv = $obs[$wk];
                if ((is_int($wv) && $wv >= 0) || (is_array($wv) && array_is_list($wv))) {
                    $checked = true;
                    if ((is_int($wv) ? $wv : count($wv)) > 0) throw new RuntimeException("{$lbl}: expected 0 writes");
                } else throw new RuntimeException("frame.invalid:{$res}: {$wk} must be a non-negative integer");
            }
            if (array_key_exists('before', $obs) && array_key_exists('after', $obs)) {
                $checked = true;
                if (!self::valuesEqual($obs['before'], $obs['after'])) throw new RuntimeException("{$lbl}: snapshots differ");
            }
        }
        if (!$checked) throw new RuntimeException("frame.invalid:{$res}: missing writes or snapshots");
    }

    public static function checkFrame(array $contractView, string $caseId, array $frames, array &$readKeys): void
    {
        $scopeWrites = $contractView['scope']['writes'] ?? [];
        $caseDef = $contractView['cases'][$caseId] ?? [];
        $hasCw = array_key_exists('writes', $caseDef) && is_array($caseDef['writes']);
        $allowed = $hasCw ? $caseDef['writes'] : $scopeWrites;
        $checked = [];
        if ($hasCw) {
            foreach ($scopeWrites as $res) {
                $base = explode('#', (string)$res)[0];
                if (!in_array($res, $allowed, true) && !in_array($base, $allowed, true)) {
                    $checked[] = (string)$res;
                    $checked[] = $base;
                    if (!array_key_exists($res, $frames) && !array_key_exists($base, $frames)) continue;
                    $obs = array_key_exists($res, $frames) ? $frames[$res] : $frames[$base];
                    $hasM = is_array($obs) && !array_is_list($obs) && (array_key_exists('writes', $obs) || array_key_exists('operations', $obs) || array_key_exists('events', $obs) || (array_key_exists('before', $obs) && array_key_exists('after', $obs)));
                    if ($hasM) self::verifySinglePhpFrame((string)$res, $obs, false);
                    if (is_array($obs) && !array_is_list($obs) && ($obs['observed'] ?? null) === false) continue;
                    if (!$hasM) self::verifySinglePhpFrame((string)$res, $obs, false);
                    $readKeys[] = "@frame:{$res}";
                } else $readKeys[] = "@frame:{$res}";
            }
        }
        foreach ($frames as $fk => $fObs) {
            $base = explode('#', (string)$fk)[0];
            if (!in_array((string)$fk, $checked, true) && !in_array((string)$fk, $allowed, true) && !in_array($base, $allowed, true)) self::verifySinglePhpFrame((string)$fk, $fObs, true);
        }
    }

    private static function applyScale(mixed $out, float $ratio): mixed
    {
        if ($ratio == 1.0 || !is_array($out) || array_is_list($out)) return self::isFiniteNum($out) ? $out * $ratio : $out;
        $scale = fn($v) => self::isFiniteNum($v) ? $v * $ratio : $v;
        foreach (['eq', 'approx', 'min', 'max', 'abs_tol', 'step_max_delta'] as $k) if (array_key_exists($k, $out)) $out[$k] = $scale($out[$k]);
        foreach (['in', 'not_in'] as $k) if (is_array($out[$k] ?? null)) $out[$k] = array_map($scale, $out[$k]);
        if (array_key_exists('sum_total', $out)) $out['sum_total'] = is_array($out['sum_total']) ? array_map($scale, $out['sum_total']) : $scale($out['sum_total']);
        return $out;
    }

    private static function unwrapOrDesugar03(mixed $raw, array $units = [], ?string $predUnit = null, ?float $preConv = null): mixed
    {
        if (!is_array($raw) || array_is_list($raw)) return $preConv !== null && self::isFiniteNum($raw) ? $raw * $preConv : $raw;
        if (count($raw) === 1 && array_key_exists('eq', $raw) && !is_array($raw['eq'])) return $preConv !== null && self::isFiniteNum($raw['eq']) ? $raw['eq'] * $preConv : $raw['eq'];
        $out = [];
        foreach ($raw as $k => $v) {
            if ($k === 'eq') $out[array_key_exists('tol', $raw) ? 'approx' : 'eq'] = $v;
            elseif ($k === 'len' && is_array($v)) { if (isset($v['min'])) $out['min_len'] = $v['min']; if (isset($v['max'])) $out['max_len'] = $v['max']; }
            elseif ($k === 'keys' && is_array($v)) { if (isset($v['allow'])) $out['allowed_keys'] = $v['allow']; if (isset($v['forbid'])) $out['forbid_keys'] = $v['forbid']; }
            elseif ($k === 'tol' && is_array($v)) { if (isset($v['abs'])) $out['abs_tol'] = $v['abs']; if (isset($v['rel'])) $out['rel_tol'] = $v['rel']; }
            elseif ($k === 'peer' && is_array($v)) {
                foreach (['eq' => 'eq_field', 'le' => 'le_field', 'ge' => 'ge_field', 'sum' => 'sum_fields', 'balance' => 'balance_fields'] as $pk => $rk) if (isset($v[$pk])) $out[$rk] = $v[$pk];
            } elseif ($k === 'series' && is_array($v)) {
                foreach ($v as $sk => $sv) $out[$sk] = $sk === 'monotonic' && in_array($sv, ['increasing', 'decreasing'], true) ? "strictly_{$sv}" : $sv;
            } elseif ($k !== 'convert_from') $out[$k] = $v;
        }
        if ($preConv !== null) return self::applyScale($out, $preConv);
        if (array_key_exists('convert_from', $raw)) {
            $from = $raw['convert_from'];
            $target = $predUnit ?? $raw['unit'] ?? null;
            if (!$units && is_array($raw['unit_conversion'] ?? null)) $units = $raw['unit_conversion'];
            $matches = array_filter(array_keys($units), fn($k) => str_starts_with((string)$k, "{$from}->"));
            $ratio = $target === $from ? 1.0 : ($units[$target !== null ? "{$from}->{$target}" : (count($matches) === 1 ? reset($matches) : '')] ?? null);
            if (!self::isFiniteNum($ratio) || $ratio <= 0) throw new RuntimeException("missing unit conversion from {$from}");
            return self::applyScale($out, (float)$ratio);
        }
        return $out;
    }

    public static function runPlanCase(array $planDoc, string $caseId, array $observed, array $frames = []): array
    {
        $pc = $planDoc['cases'][$caseId] ?? null;
        if (!is_array($pc)) throw new RuntimeException("unknown case {$caseId}");
        $readKeys = [];
        foreach (($pc['clauses'] ?? []) as $cl) {
            $pred = (string)($cl['pred'] ?? '');
            $ptr = (string)($cl['pointer'] ?? "/{$pred}");
            $conv = (float)($cl['conv'] ?? 1.0);
            $exp = self::unwrapOrDesugar03($cl['constraint'] ?? [], [], null, $conv);
            $peerPtrs = [];
            foreach (($cl['peer_pointers'] ?? []) as $pk => $pv) {
                $peerPtrs[(string)$pk] = (string)$pv;
                if (str_starts_with((string)$pk, 'then.')) $peerPtrs[substr((string)$pk, 5)] = (string)$pv;
            }
            $whenEnv = array_replace($pc['when'] ?? [], $cl['when_peers'] ?? []);
            [$present, $actual] = self::resolvePointer($observed, $ptr);
            if (!$present && array_key_exists($pred, $observed)) [$present, $actual] = [true, $observed[$pred]];
            if (!$present && is_array($exp) && (isset($exp['forbid_keys']) || isset($exp['allowed_keys']))) [$present, $actual] = [true, $observed];
            self::checkValue($pred, $actual, $exp, $present, $observed, $peerPtrs, $whenEnv);
            if (str_starts_with((string)($cl['clause'] ?? ''), 'then.')) $readKeys[] = $pred;
        }
        $allowed = $pc['permitted_writes'] ?? [];
        foreach ($frames as $fk => $fObs) {
            $base = explode('#', (string)$fk)[0];
            if (!in_array((string)$fk, $allowed, true) && !in_array($base, $allowed, true)) self::verifySinglePhpFrame((string)$fk, $fObs, true);
        }
        return ['verified' => true, 'read' => array_values(array_unique($readKeys))];
    }

    public static function runProjectionChecks(array $contractView, string $caseId, array $observed, array $frames = []): array
    {
        if (($contractView['schema'] ?? '') === 'drift.bridge-plan/1') return self::runPlanCase($contractView, $caseId, $observed, $frames);
        $caseDef = $contractView['cases'][$caseId] ?? null;
        if (!is_array($caseDef)) throw new RuntimeException("unknown case {$caseId}");
        $is03 = ($contractView['drift'] ?? '') === '0.3';
        $thenTable = $caseDef['then'] ?? [];
        $projThen = $contractView['projections']['then'] ?? [];
        $readKeys = [];
        $whenEnv = [];
        foreach (($caseDef['when'] ?? []) as $wk => $wv) $whenEnv[$wk] = $is03 ? self::unwrapOrDesugar03($wv) : $wv;
        foreach ($thenTable as $key => $rawExpected) {
            $expected = $is03 ? self::unwrapOrDesugar03($rawExpected, $contractView['units'] ?? [], $contractView['schema']['then'][$key]['unit'] ?? null) : $rawExpected;
            [$present, $actual] = self::resolvePointer($observed, (string)($projThen[$key] ?? "/{$key}"));
            if (!$present && array_key_exists((string)$key, $observed)) [$present, $actual] = [true, $observed[(string)$key]];
            if (!$present && is_array($expected) && (isset($expected['forbid_keys']) || isset($expected['allowed_keys']))) [$present, $actual] = [true, $observed];
            self::checkValue((string)$key, $actual, $expected, $present, $observed, $projThen, $whenEnv);
            $readKeys[] = (string)$key;
        }
        self::checkFrame($contractView, $caseId, $frames, $readKeys);
        $reqFrames = (array_key_exists('writes', $caseDef) && is_array($caseDef['writes'])) ? array_map(fn($r) => "@frame:{$r}", $contractView['scope']['writes'] ?? []) : [];
        $allRead = array_reduce(array_merge(array_keys($thenTable), $reqFrames), fn($ok, $k) => $ok && in_array((string)$k, $readKeys, true), true);
        return ['verified' => $allRead, 'read' => array_values(array_unique($readKeys))];
    }

    public static function replayCounterexamples(array $contractView, string $caseId, array $fixtures, callable $runner, array $frames = []): int
    {
        $cid = (string)($contractView['id'] ?? '');
        $count = 0;
        foreach ($fixtures as $fx) {
            if (($fx['contract'] ?? '') === $cid && ($fx['case'] ?? '') === $caseId) {
                self::runProjectionChecks($contractView, $caseId, $runner($fx['witness']['when'] ?? []), $frames);
                $count++;
            }
        }
        return $count;
    }

    public static function emitProofShard(string $eventsPath, array $contractView, array $runs, array $phpInputs, array $envMeta = []): void
    {
        [$lines, $tests, $classes, $inputsMap] = [[], [], [], []];
        foreach ($runs as $r) {
            $testId = (string)$r['test'];
            $tests[] = $testId;
            $cls = explode('#', $testId)[0];
            if (!in_array($cls, $classes, true)) $classes[] = $cls;
            $inputsMap[$testId] = $phpInputs;
            $ev = ['contract' => (string)$contractView['id'], 'digest' => (string)$contractView['digest'], 'cases' => $r['cases'], 'level' => (string)($r['level'] ?? 'unit'), 'test' => $testId, 'outcome' => (string)$r['outcome']];
            if (!empty($r['read'])) $ev['read'] = $r['read'];
            if (($contractView['drift'] ?? '') === '0.3') { $ev['schema'] = '0.3'; $ev['capabilities'] = ['rel-keys-guard/1', 'rel-peer-sum/1', 'rel-tol/1']; }
            $lines[] = json_encode($ev, JSON_UNESCAPED_SLASHES);
        }
        file_put_contents($eventsPath, implode("\n", $lines) . "\n");
        $meta = ['version' => 1, 'classes' => $classes, 'tests' => $tests, 'inputs' => $inputsMap, 'env' => array_merge(['toolchain' => self::BRIDGE_RUNTIME_BASELINE, 'deps' => 'composer-lock-0', 'config' => 'phpunit-1', 'runner' => 'phpunit', 'drift' => '0.7.0', 'adapter' => self::VERSION, 'policy' => 'core@1'], $envMeta)];
        file_put_contents((string)preg_replace('/\.jsonl$/', '.meta.json', $eventsPath), json_encode($meta, JSON_UNESCAPED_SLASHES) . "\n");
    }
}
