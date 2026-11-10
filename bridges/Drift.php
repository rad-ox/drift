<?php
declare(strict_types=1);

namespace Drift;

use RuntimeException;

/**
 * Zero-dependency PHP 8.2+ forward verification bridge for DRIFT.
 * Conforms to drift.bridge-capabilities/1.
 */
final class Drift
{
    public const VERSION = 'drift.php@0.5.1';
    public const BRIDGE_RUNTIME_BASELINE = 'php-8.2-cli';
    public const CAPABILITIES = [
        'predicates',
        'projections',
        'forbid_keys',
        'not_in',
        'case_frames',
        'counterexample_replay',
        'in_process_mutants',
    ];

    public static function bridgeCapabilities(): array
    {
        return [
            'schema' => 'drift.bridge-capabilities/1',
            'bridge' => 'drift.php',
            'version' => self::VERSION,
            'runtime_baseline' => self::BRIDGE_RUNTIME_BASELINE,
            'capabilities' => self::CAPABILITIES,
        ];
    }

    public static function requireCapabilities(array $required): void
    {
        foreach ($required as $cap) {
            if (!in_array((string)$cap, self::CAPABILITIES, true)) {
                throw new RuntimeException('bridge.capability_unsupported:' . (string)$cap);
            }
        }
    }

    public static function resolvePointer(array $doc, string $pointer): array
    {
        if ($pointer === '' || $pointer === '/') {
            return [true, $doc];
        }
        if ($pointer[0] !== '/') {
            return [array_key_exists($pointer, $doc), $doc[$pointer] ?? null];
        }
        $cur = $doc;
        $segs = explode('/', substr($pointer, 1));
        foreach ($segs as $rawSeg) {
            $seg = str_replace(['~1', '~0'], ['/', '~'], $rawSeg);
            if (!is_array($cur) || !array_key_exists($seg, $cur)) {
                return [false, null];
            }
            $cur = $cur[$seg];
        }
        return [true, $cur];
    }

    public const SUPPORTED_REL_KEYS = [
        'eq',
        'in',
        'not_in',
        'min',
        'max',
        'len',
        'min_len',
        'max_len',
        'non_empty',
        'prefix',
        'suffix',
        'contains',
        'forbid_keys',
        'allowed_keys',
        'le_field',
        'ge_field',
        'eq_field',
        'sum_fields',
        'monotonic',
        'step_max_delta',
        'sum_total',
        'approx',
        'abs_tol',
        'rel_tol',
        'balance_fields',
        'unit',
        'unit_conversion',
    ];

    private static function isFiniteNum(mixed $v): bool
    {
        return (is_int($v) || is_float($v)) && !is_nan((float)$v) && !is_infinite((float)$v);
    }

    private static function valuesEqual(mixed $a, mixed $b): bool
    {
        if (is_bool($a) || is_bool($b)) {
            return is_bool($a) && is_bool($b) && $a === $b;
        }
        if (self::isFiniteNum($a) || self::isFiniteNum($b)) {
            return self::isFiniteNum($a) && self::isFiniteNum($b) && abs((float)$a - (float)$b) <= 1e-9;
        }
        if ($a === null || $b === null) {
            return $a === null && $b === null;
        }
        if (is_array($a) && is_array($b)) {
            if (count($a) !== count($b)) {
                return false;
            }
            if (array_is_list($a) && array_is_list($b)) {
                foreach ($a as $idx => $av) {
                    if (!self::valuesEqual($av, $b[$idx])) {
                        return false;
                    }
                }
                return true;
            }
            foreach ($a as $k => $av) {
                if (!array_key_exists($k, $b) || !self::valuesEqual($av, $b[$k])) {
                    return false;
                }
            }
            return true;
        }
        return $a === $b;
    }

    private static function hasKeyRecursive(mixed $val, string $fk, bool $isRoot = true): bool
    {
        if (!is_array($val)) {
            return false;
        }
        if (array_is_list($val)) {
            foreach ($val as $item) {
                if (self::hasKeyRecursive($item, $fk, false)) {
                    return true;
                }
            }
            return false;
        }
        if (array_key_exists($fk, $val)) {
            return true;
        }
        foreach ($val as $k => $v) {
            if ($isRoot && (string)$k === '_frame' && $fk !== '_frame' && is_array($v)) {
                continue;
            }
            if (self::hasKeyRecursive($v, $fk, false)) {
                return true;
            }
        }
        return false;
    }

    public static function checkValue(string $key, mixed $actual, mixed $expected, bool $actualPresent = true, array $observed = [], array $projThen = [], array $whenEnv = []): void
    {
        if (is_float($actual) && (is_nan($actual) || is_infinite($actual))) {
            throw new RuntimeException("then.{$key}: non-finite float value is forbidden");
        }
        if (!is_array($expected) || array_is_list($expected)) {
            if (!$actualPresent || !self::valuesEqual($actual, $expected)) {
                throw new RuntimeException("then.{$key}: expected " . json_encode($expected) . ', got ' . json_encode($actual));
            }
            return;
        }
        if (empty($expected)) {
            throw new RuntimeException("then.{$key}: empty predicate object is unsupported");
        }
        foreach (array_keys($expected) as $op) {
            if (!in_array((string)$op, self::SUPPORTED_REL_KEYS, true)) {
                throw new RuntimeException("then.{$key}: unsupported predicate operator {$op}");
            }
        }
        $len = is_string($actual) ? (function_exists('mb_strlen') ? mb_strlen($actual, 'UTF-8') : preg_match_all('/./us', $actual)) : (is_array($actual) ? count($actual) : -1);
        if (array_key_exists('eq', $expected) && (!$actualPresent || !self::valuesEqual($actual, $expected['eq']))) {
            throw new RuntimeException("then.{$key}: eq violation");
        }
        $series = array_key_exists('monotonic', $expected) || array_key_exists('sum_total', $expected) || array_key_exists('step_max_delta', $expected);
        if (array_key_exists('in', $expected)) {
            if (!is_array($expected['in']) || !$actualPresent) {
                throw new RuntimeException("then.{$key}: value " . json_encode($actual) . ' not in allowed set');
            }
            $foundIn = false;
            foreach ($expected['in'] as $cand) {
                if (self::valuesEqual($actual, $cand)) {
                    $foundIn = true;
                    break;
                }
            }
            if (!$foundIn) {
                throw new RuntimeException("then.{$key}: value " . json_encode($actual) . ' not in allowed set');
            }
        }
        if (array_key_exists('not_in', $expected)) {
            if (!$actualPresent || $actual === null) {
                throw new RuntimeException("then.{$key}: expected non-null value for not_in");
            }
            if (is_array($expected['not_in'])) {
                foreach ($expected['not_in'] as $forb) {
                    if (self::valuesEqual($actual, $forb)) {
                        throw new RuntimeException("then.{$key}: value " . json_encode($actual) . ' is forbidden by not_in');
                    }
                }
            } elseif (!self::valuesEqual($actual, $expected['not_in'])) {
                throw new RuntimeException("then.{$key}: pick-forbidden-value mutant on not_in killed");
            }
        }
        if (array_key_exists('approx', $expected)) {
            $at = array_key_exists('abs_tol', $expected) && self::isFiniteNum($expected['abs_tol']) ? (float)$expected['abs_tol'] : 0.0;
            $rt = array_key_exists('rel_tol', $expected) && self::isFiniteNum($expected['rel_tol']) ? (float)$expected['rel_tol'] : 0.0;
            if (!self::isFiniteNum($actual) || !self::isFiniteNum($expected['approx']) || (!array_key_exists('abs_tol', $expected) && !array_key_exists('rel_tol', $expected)) || $at < 0.0 || $rt < 0.0) {
                throw new RuntimeException("then.{$key}: invalid approx");
            }
            $ap = (float)$expected['approx'];
            if (abs((float)$actual - $ap) > $at + $rt * abs($ap)) {
                throw new RuntimeException("then.{$key}: " . json_encode($actual) . " outside approx {$ap}");
            }
        }
        if (!$series && array_key_exists('min', $expected)) {
            if (!self::isFiniteNum($actual) || !self::isFiniteNum($expected['min']) || (float)$actual + 1e-9 < (float)$expected['min']) {
                throw new RuntimeException("then.{$key}: " . json_encode($actual) . " < min {$expected['min']}");
            }
        }
        if (!$series && array_key_exists('max', $expected)) {
            if (!self::isFiniteNum($actual) || !self::isFiniteNum($expected['max']) || (float)$actual - 1e-9 > (float)$expected['max']) {
                throw new RuntimeException("then.{$key}: " . json_encode($actual) . " > max {$expected['max']}");
            }
        }
        if (array_key_exists('len', $expected)) {
            if (!is_int($expected['len']) || $expected['len'] < 0 || $len !== $expected['len']) {
                throw new RuntimeException("then.{$key}: length {$len} != {$expected['len']}");
            }
        }
        if (array_key_exists('min_len', $expected)) {
            if (!is_int($expected['min_len']) || $expected['min_len'] < 0 || $len < 0 || $len < $expected['min_len']) {
                throw new RuntimeException("then.{$key}: length {$len} < min_len {$expected['min_len']}");
            }
        }
        if (array_key_exists('max_len', $expected)) {
            if (!is_int($expected['max_len']) || $expected['max_len'] < 0 || $len < 0 || $len > $expected['max_len']) {
                throw new RuntimeException("then.{$key}: length {$len} > max_len {$expected['max_len']}");
            }
        }
        if (array_key_exists('non_empty', $expected)) {
            $wantNe = $expected['non_empty'];
            if (!is_bool($wantNe) || $len < 0 || ($wantNe ? $len <= 0 : $len !== 0)) {
                throw new RuntimeException("then.{$key}: non_empty violation (len={$len})");
            }
        }
        if (array_key_exists('prefix', $expected)) {
            $pfx = $expected['prefix'];
            if (!is_string($pfx) || !is_string($actual) || !str_starts_with($actual, $pfx)) {
                throw new RuntimeException("then.{$key}: expected prefix {$pfx}, got " . json_encode($actual));
            }
        }
        if (array_key_exists('suffix', $expected)) {
            $sfx = $expected['suffix'];
            if (!is_string($sfx) || !is_string($actual) || !str_ends_with($actual, $sfx)) {
                throw new RuntimeException("then.{$key}: expected suffix {$sfx}, got " . json_encode($actual));
            }
        }
        if (array_key_exists('contains', $expected)) {
            $cExp = $expected['contains'];
            $okContains = false;
            if (is_string($actual)) {
                if (is_string($cExp)) {
                    $okContains = str_contains($actual, $cExp);
                } elseif (is_array($cExp) && array_is_list($cExp)) {
                    $okContains = true;
                    foreach ($cExp as $sub) {
                        if (!is_string($sub) || !str_contains($actual, $sub)) {
                            $okContains = false;
                            break;
                        }
                    }
                }
            } elseif (is_array($actual) && array_is_list($actual)) {
                $reqs = (is_array($cExp) && array_is_list($cExp)) ? $cExp : [$cExp];
                $okContains = true;
                foreach ($reqs as $req) {
                    $foundItem = false;
                    foreach ($actual as $actItem) {
                        if (self::valuesEqual($actItem, $req)) {
                            $foundItem = true;
                            break;
                        }
                    }
                    if (!$foundItem) {
                        $okContains = false;
                        break;
                    }
                }
            }
            if (!$okContains) {
                throw new RuntimeException("then.{$key}: contains violation");
            }
        }
        if (array_key_exists('forbid_keys', $expected)) {
            if (!is_array($actual) || (array_is_list($actual) && !empty($actual))) {
                throw new RuntimeException("then.{$key}: expected object for forbid_keys");
            }
            $isRoot = ($actual === $observed);
            if (is_array($expected['forbid_keys'])) {
                foreach ($expected['forbid_keys'] as $fk) {
                    if (self::hasKeyRecursive($actual, (string)$fk, $isRoot)) {
                        throw new RuntimeException("then.{$key}: forbidden key {$fk} is present");
                    }
                }
            } elseif (is_string($expected['forbid_keys'])) {
                if (!self::hasKeyRecursive($actual, $expected['forbid_keys'], $isRoot)) {
                    throw new RuntimeException("then.{$key}: drop-forbid-key mutant killed");
                }
            } else {
                throw new RuntimeException("then.{$key}: invalid forbid_keys");
            }
        }
        if (array_key_exists('allowed_keys', $expected)) {
            if (!is_array($actual) || !is_array($expected['allowed_keys'])) {
                throw new RuntimeException("then.{$key}: expected object for allowed_keys");
            }
            foreach (array_keys($actual) as $ak) {
                if ((string)$ak === '_frame' && is_array($actual[$ak])) {
                    continue;
                }
                if (!in_array((string)$ak, $expected['allowed_keys'], true)) {
                    throw new RuntimeException("then.{$key}: key {$ak} is outside allowed_keys");
                }
            }
        }
        $tol = $expected['abs_tol'] ?? 1e-9;
        foreach (['le_field', 'ge_field', 'eq_field'] as $op) {
            if (!array_key_exists($op, $expected)) continue;
            [$found, $peer] = self::resolvePeer($observed, $projThen, $expected[$op], $whenEnv);
            $ok = $found && ($op === 'eq_field' ? self::valuesEqual($actual, $peer)
                : (self::isFiniteNum($actual) && self::isFiniteNum($peer)
                    && ($op === 'le_field' ? $actual - $tol <= $peer : $actual + $tol >= $peer)));
            if (!$ok) throw new RuntimeException("then.{$key}: {$op} violation");
        }
        foreach (['sum_fields', 'balance_fields'] as $op) {
            if (!array_key_exists($op, $expected)) continue;
            $expr = $expected[$op];
            if (!is_array($expr) || !self::isFiniteNum($actual) || ($op === 'sum_fields' && count($expr) < 2)) {
                throw new RuntimeException("then.{$key}: invalid {$op}");
            }
            $sides = $op === 'sum_fields' ? ['add' => $expr] : $expr;
            $total = 0.0;
            foreach (['add' => 1, 'sub' => -1] as $side => $sign) {
                foreach (($sides[$side] ?? []) as $ref) {
                    [$found, $peer] = self::resolvePeer($observed, $projThen, $ref, $whenEnv);
                    if (!$found || !self::isFiniteNum($peer)) throw new RuntimeException("then.{$key}: missing numeric peer {$ref}");
                    $total += $sign * $peer;
                }
            }
            if (!is_finite($total) || abs($actual - $total) > $tol) throw new RuntimeException("then.{$key}: {$op} violation");
        }
        if ($series) {
            if (!is_array($actual) || !$actual || ((array_key_exists('monotonic', $expected) || array_key_exists('step_max_delta', $expected)) && !array_is_list($actual))) {
                throw new RuntimeException("then.{$key}: expected non-empty numeric sequence");
            }
            $values = array_values($actual);
            foreach ($values as $i => $value) {
                if (!self::isFiniteNum($value)) throw new RuntimeException("then.{$key}: non-numeric sequence");
                if ((array_key_exists('min', $expected) && $value + $tol < $expected['min']) || (array_key_exists('max', $expected) && $value - $tol > $expected['max'])) {
                    throw new RuntimeException("then.{$key}: sequence element outside bounds");
                }
                if ($i === 0) continue;
                $prev = $values[$i - 1];
                if (array_key_exists('monotonic', $expected)) {
                    $ok = match ($expected['monotonic']) {
                        'non_decreasing' => $prev - $tol <= $value,
                        'non_increasing' => $prev + $tol >= $value,
                        'strictly_increasing' => $prev + $tol < $value,
                        'strictly_decreasing' => $prev - $tol > $value,
                        default => false,
                    };
                    if (!$ok) throw new RuntimeException("then.{$key}: monotonic violation");
                }
                if (array_key_exists('step_max_delta', $expected) && (!self::isFiniteNum($expected['step_max_delta']) || $expected['step_max_delta'] <= 0 || abs($value - $prev) > $expected['step_max_delta'] + $tol)) {
                    throw new RuntimeException("then.{$key}: step_max_delta violation");
                }
            }
            if (array_key_exists('sum_total', $expected)) {
                $total = array_sum($values);
                $bounds = is_array($expected['sum_total']) ? $expected['sum_total'] : ['eq' => $expected['sum_total']];
                if (!is_finite((float)$total) || !$bounds) throw new RuntimeException("then.{$key}: invalid sum_total");
                foreach ($bounds as $op => $bound) {
                    if (!self::isFiniteNum($bound) || !match ($op) {
                        'eq' => abs($total - $bound) <= $tol,
                        'min' => $total + $tol >= $bound,
                        'max' => $total - $tol <= $bound,
                        default => false,
                    }) throw new RuntimeException("then.{$key}: sum_total violation");
                }
            }
        }
    }

    private static function resolvePeer(array $observed, array $projThen, mixed $ref, array $whenEnv): array
    {
        if (!is_string($ref) || $ref === '') return [false, null];
        if (str_starts_with($ref, 'when.')) {
            if (array_key_exists($ref, $observed)) return [true, $observed[$ref]];
            $inputs = array_replace($whenEnv, $observed['_when_env'] ?? [], $observed['before'] ?? [], $observed['when'] ?? []);
            $key = substr($ref, 5);
            return [array_key_exists($key, $inputs), $inputs[$key] ?? null];
        }
        if (str_starts_with($ref, 'then.')) $ref = substr($ref, 5);
        return self::resolvePointer($observed, $projThen[$ref] ?? (str_starts_with($ref, '/') ? $ref : '/' . str_replace(['~', '/'], ['~0', '~1'], $ref)));
    }

    private static function verifySinglePhpFrame(string $res, mixed $obs, bool $isAmbient): void
    {
        $checked = false;
        $label = $isAmbient ? "undeclared write on perimeter resource \"{$res}\"" : "frame.violation:{$res}";
        if (is_int($obs) && $obs >= 0) {
            $checked = true;
            if ($obs > 0) {
                throw new RuntimeException("{$label}: expected 0 writes, observed {$obs}");
            }
        } elseif (is_array($obs) && !array_is_list($obs)) {
            foreach (['writes', 'operations', 'events'] as $wk) {
                if (array_key_exists($wk, $obs)) {
                    $wv = $obs[$wk];
                    if (is_int($wv) && $wv >= 0) {
                        $checked = true;
                        if ($wv > 0) {
                            throw new RuntimeException("{$label}: expected 0 writes, observed {$wv}");
                        }
                    } elseif (is_array($wv) && array_is_list($wv)) {
                        $checked = true;
                        if (count($wv) > 0) {
                            throw new RuntimeException("{$label}: expected 0 writes, observed " . count($wv));
                        }
                    } else {
                        throw new RuntimeException("frame.invalid:{$res}: {$wk} must be a non-negative integer");
                    }
                }
            }
            if (array_key_exists('before', $obs) && array_key_exists('after', $obs)) {
                $checked = true;
                if (!self::valuesEqual($obs['before'], $obs['after'])) {
                    throw new RuntimeException("{$label}: before and after snapshots differ");
                }
            }
        }
        if (!$checked) {
            throw new RuntimeException("frame.invalid:{$res}: must supply non-negative integer writes or before/after snapshots");
        }
    }

    public static function checkFrame(array $contractView, string $caseId, array $frames, array &$readKeys): void
    {
        $scopeWrites = $contractView['scope']['writes'] ?? [];
        $caseDef = $contractView['cases'][$caseId] ?? [];
        $hasCaseWrites = array_key_exists('writes', $caseDef) && is_array($caseDef['writes']);
        $allowedCaseWrites = $hasCaseWrites ? $caseDef['writes'] : $scopeWrites;
        $checkedKeys = [];
        if ($hasCaseWrites) {
            foreach ($scopeWrites as $res) {
                $baseRes = explode('#', (string)$res)[0];
                if (!in_array($res, $allowedCaseWrites, true) && !in_array($baseRes, $allowedCaseWrites, true)) {
                    $checkedKeys[] = (string)$res;
                    $checkedKeys[] = $baseRes;
                    if (!array_key_exists($res, $frames) && !array_key_exists($baseRes, $frames)) {
                        continue;
                    }
                    $obs = array_key_exists($res, $frames) ? $frames[$res] : $frames[$baseRes];
                    $hasMetrics = is_array($obs) && !array_is_list($obs) && (array_key_exists('writes', $obs) || array_key_exists('operations', $obs) || array_key_exists('events', $obs) || (array_key_exists('before', $obs) && array_key_exists('after', $obs)));
                    if ($hasMetrics) {
                        self::verifySinglePhpFrame((string)$res, $obs, false);
                    }
                    if (is_array($obs) && !array_is_list($obs) && ($obs['observed'] ?? null) === false) {
                        continue;
                    }
                    if (!$hasMetrics) {
                        self::verifySinglePhpFrame((string)$res, $obs, false);
                    }
                    $readKeys[] = "@frame:{$res}";
                } else {
                    $readKeys[] = "@frame:{$res}";
                }
            }
        }
        foreach ($frames as $fk => $fObs) {
            $baseFk = explode('#', (string)$fk)[0];
            if (in_array((string)$fk, $checkedKeys, true) || in_array((string)$fk, $allowedCaseWrites, true) || in_array($baseFk, $allowedCaseWrites, true)) {
                continue;
            }
            self::verifySinglePhpFrame((string)$fk, $fObs, true);
        }
    }

    private static function unwrapOrDesugar03(mixed $raw, array $units = [], ?string $predUnit = null): mixed
    {
        if (!is_array($raw) || array_is_list($raw)) {
            return $raw;
        }
        if (count($raw) === 1 && array_key_exists('eq', $raw) && !is_array($raw['eq'])) {
            return $raw['eq'];
        }
        $out = [];
        foreach ($raw as $k => $v) {
            if ($k === 'eq') {
                if (array_key_exists('tol', $raw)) {
                    $out['approx'] = $v;
                } else {
                    $out['eq'] = $v;
                }
            } elseif ($k === 'len' && is_array($v)) {
                if (array_key_exists('min', $v)) $out['min_len'] = $v['min'];
                if (array_key_exists('max', $v)) $out['max_len'] = $v['max'];
            } elseif ($k === 'keys' && is_array($v)) {
                if (array_key_exists('allow', $v)) $out['allowed_keys'] = $v['allow'];
                if (array_key_exists('forbid', $v)) $out['forbid_keys'] = $v['forbid'];
            } elseif ($k === 'tol' && is_array($v)) {
                if (array_key_exists('abs', $v)) $out['abs_tol'] = $v['abs'];
                if (array_key_exists('rel', $v)) $out['rel_tol'] = $v['rel'];
            } elseif ($k === 'peer' && is_array($v)) {
                if (array_key_exists('eq', $v)) $out['eq_field'] = $v['eq'];
                if (array_key_exists('le', $v)) $out['le_field'] = $v['le'];
                if (array_key_exists('ge', $v)) $out['ge_field'] = $v['ge'];
                if (array_key_exists('sum', $v) && is_array($v['sum'])) {
                    $out['sum_fields'] = $v['sum'];
                }
                if (array_key_exists('balance', $v)) $out['balance_fields'] = $v['balance'];
            } elseif ($k === 'series' && is_array($v)) {
                foreach ($v as $sk => $sv) {
                    $out[$sk] = $sk === 'monotonic' && in_array($sv, ['increasing', 'decreasing'], true) ? "strictly_{$sv}" : $sv;
                }
            } elseif ($k !== 'convert_from') {
                $out[$k] = $v;
            }
        }
        if (array_key_exists('convert_from', $raw)) {
            $from = $raw['convert_from'];
            $target = $predUnit ?? $raw['unit'] ?? null;
            if (!$units && is_array($raw['unit_conversion'] ?? null)) $units = $raw['unit_conversion'];
            $matches = array_filter(array_keys($units), fn($k) => str_starts_with((string)$k, "{$from}->"));
            $ratio = $target === $from ? 1 : ($units[$target !== null ? "{$from}->{$target}" : (count($matches) === 1 ? reset($matches) : '')] ?? null);
            if (!self::isFiniteNum($ratio) || $ratio <= 0) throw new RuntimeException("missing unit conversion from {$from}");
            $scale = fn($v) => self::isFiniteNum($v) ? $v * $ratio : $v;
            foreach (['eq', 'approx', 'min', 'max', 'abs_tol', 'step_max_delta'] as $k) {
                if (array_key_exists($k, $out)) $out[$k] = $scale($out[$k]);
            }
            foreach (['in', 'not_in'] as $k) {
                if (is_array($out[$k] ?? null)) $out[$k] = array_map($scale, $out[$k]);
            }
            if (array_key_exists('sum_total', $out)) $out['sum_total'] = is_array($out['sum_total']) ? array_map($scale, $out['sum_total']) : $scale($out['sum_total']);
        }
        return $out;
    }

    public static function runProjectionChecks(array $contractView, string $caseId, array $observed, array $frames = []): array
    {
        $caseDef = $contractView['cases'][$caseId] ?? null;
        if (!is_array($caseDef)) {
            throw new RuntimeException("unknown case {$caseId}");
        }
        $is03 = ($contractView['drift'] ?? '') === '0.3';
        $thenTable = $caseDef['then'] ?? [];
        $projThen = $contractView['projections']['then'] ?? [];
        $readKeys = [];
        $whenEnv = [];
        foreach (($caseDef['when'] ?? []) as $wk => $wv) $whenEnv[$wk] = $is03 ? self::unwrapOrDesugar03($wv) : $wv;
        foreach ($thenTable as $key => $rawExpected) {
            $expected = $is03 ? self::unwrapOrDesugar03($rawExpected, $contractView['units'] ?? [], $contractView['schema']['then'][$key]['unit'] ?? null) : $rawExpected;
            $ptr = $projThen[$key] ?? "/{$key}";
            [$present, $actual] = self::resolvePointer($observed, (string)$ptr);
            if (!$present && array_key_exists((string)$key, $observed)) {
                $present = true;
                $actual = $observed[(string)$key];
            }
            if (!$present && is_array($expected) && (array_key_exists('forbid_keys', $expected) || array_key_exists('allowed_keys', $expected))) {
                $present = true;
                $actual = $observed;
            }
            self::checkValue((string)$key, $actual, $expected, $present, $observed, $projThen, $whenEnv);
            $readKeys[] = (string)$key;
        }
        self::checkFrame($contractView, $caseId, $frames, $readKeys);
        $requiredFrames = [];
        if (array_key_exists('writes', $caseDef) && is_array($caseDef['writes'])) {
            foreach (($contractView['scope']['writes'] ?? []) as $res) {
                $requiredFrames[] = "@frame:{$res}";
            }
        }
        $allRead = true;
        foreach (array_keys($thenTable) as $k) {
            if (!in_array((string)$k, $readKeys, true)) {
                $allRead = false;
            }
        }
        foreach ($requiredFrames as $rf) {
            if (!in_array($rf, $readKeys, true)) {
                $allRead = false;
            }
        }
        return [
            'verified' => $allRead,
            'read' => array_values(array_unique($readKeys)),
        ];
    }

    public static function replayCounterexamples(array $contractView, string $caseId, array $fixtures, callable $runner, array $frames = []): int
    {
        $cid = (string)($contractView['id'] ?? '');
        $count = 0;
        foreach ($fixtures as $fx) {
            if (($fx['contract'] ?? '') !== $cid || ($fx['case'] ?? '') !== $caseId) {
                continue;
            }
            $witnessWhen = $fx['witness']['when'] ?? [];
            $obs = $runner($witnessWhen);
            self::runProjectionChecks($contractView, $caseId, $obs, $frames);
            $count++;
        }
        return $count;
    }

    public static function emitProofShard(string $eventsPath, array $contractView, array $runs, array $phpInputs, array $envMeta = []): void
    {
        $lines = [];
        $tests = [];
        $classes = [];
        $inputsMap = [];
        foreach ($runs as $r) {
            $testId = (string)$r['test'];
            $tests[] = $testId;
            $cls = explode('#', $testId)[0];
            if (!in_array($cls, $classes, true)) {
                $classes[] = $cls;
            }
            $inputsMap[$testId] = $phpInputs;
            $ev = [
                'contract' => (string)$contractView['id'],
                'digest' => (string)$contractView['digest'],
                'cases' => $r['cases'],
                'level' => (string)($r['level'] ?? 'unit'),
                'test' => $testId,
                'outcome' => (string)$r['outcome'],
            ];
            if (!empty($r['read'])) {
                $ev['read'] = $r['read'];
            }
            if (($contractView['drift'] ?? '') === '0.3') {
                $ev['schema'] = '0.3';
                $ev['capabilities'] = ['rel-keys-guard/1', 'rel-peer-sum/1', 'rel-tol/1'];
            }
            $lines[] = json_encode($ev, JSON_UNESCAPED_SLASHES);
        }
        file_put_contents($eventsPath, implode("\n", $lines) . "\n");
        $metaPath = preg_replace('/\.jsonl$/', '.meta.json', $eventsPath);
        $meta = [
            'version' => 1,
            'classes' => $classes,
            'tests' => $tests,
            'inputs' => $inputsMap,
            'env' => array_merge([
                'toolchain' => self::BRIDGE_RUNTIME_BASELINE,
                'deps' => 'composer-lock-0',
                'config' => 'phpunit-1',
                'runner' => 'phpunit',
                'drift' => '0.5.1',
                'adapter' => self::VERSION,
                'policy' => 'core@1',
            ], $envMeta),
        ];
        file_put_contents($metaPath, json_encode($meta, JSON_UNESCAPED_SLASHES) . "\n");
    }
}
