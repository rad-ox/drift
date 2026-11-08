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
    public const VERSION = 'drift.php@0.4.0';
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

    public static function checkValue(string $key, mixed $actual, mixed $expected, bool $actualPresent = true): void
    {
        if (is_float($actual) && (is_nan($actual) || is_infinite($actual))) {
            throw new RuntimeException("then.{$key}: non-finite float value is forbidden");
        }
        if (!is_array($expected) || array_is_list($expected)) {
            if (!$actualPresent || $actual !== $expected) {
                throw new RuntimeException("then.{$key}: expected " . json_encode($expected) . ', got ' . json_encode($actual));
            }
            return;
        }
        if (array_key_exists('in', $expected) && is_array($expected['in'])) {
            if (!$actualPresent || !in_array($actual, $expected['in'], true)) {
                throw new RuntimeException("then.{$key}: value " . json_encode($actual) . ' not in allowed set');
            }
        }
        if (array_key_exists('not_in', $expected) && is_array($expected['not_in'])) {
            if ($actualPresent && in_array($actual, $expected['not_in'], true)) {
                throw new RuntimeException("then.{$key}: value " . json_encode($actual) . ' is forbidden by not_in');
            }
        }
        if (array_key_exists('min', $expected)) {
            if (!is_int($actual) && !is_float($actual)) {
                throw new RuntimeException("then.{$key}: expected numeric for min");
            }
            if ($actual < $expected['min']) {
                throw new RuntimeException("then.{$key}: {$actual} < min {$expected['min']}");
            }
        }
        if (array_key_exists('max', $expected)) {
            if (!is_int($actual) && !is_float($actual)) {
                throw new RuntimeException("then.{$key}: expected numeric for max");
            }
            if ($actual > $expected['max']) {
                throw new RuntimeException("then.{$key}: {$actual} > max {$expected['max']}");
            }
        }
        if (array_key_exists('len', $expected)) {
            $len = is_string($actual) ? strlen($actual) : (is_array($actual) ? count($actual) : -1);
            if ($len !== (int)$expected['len']) {
                throw new RuntimeException("then.{$key}: length {$len} != {$expected['len']}");
            }
        }
        if (array_key_exists('min_len', $expected)) {
            $len = is_string($actual) ? strlen($actual) : (is_array($actual) ? count($actual) : -1);
            if ($len < (int)$expected['min_len']) {
                throw new RuntimeException("then.{$key}: length {$len} < min_len {$expected['min_len']}");
            }
        }
        if (array_key_exists('max_len', $expected)) {
            $len = is_string($actual) ? strlen($actual) : (is_array($actual) ? count($actual) : -1);
            if ($len > (int)$expected['max_len']) {
                throw new RuntimeException("then.{$key}: length {$len} > max_len {$expected['max_len']}");
            }
        }
        if (array_key_exists('forbid_keys', $expected) && is_array($expected['forbid_keys'])) {
            if (!is_array($actual)) {
                throw new RuntimeException("then.{$key}: expected object for forbid_keys");
            }
            foreach ($expected['forbid_keys'] as $fk) {
                if (array_key_exists((string)$fk, $actual)) {
                    throw new RuntimeException("then.{$key}: forbidden key {$fk} is present");
                }
            }
        }
        if (array_key_exists('allowed_keys', $expected) && is_array($expected['allowed_keys'])) {
            if (!is_array($actual)) {
                throw new RuntimeException("then.{$key}: expected object for allowed_keys");
            }
            foreach (array_keys($actual) as $ak) {
                if (!in_array((string)$ak, $expected['allowed_keys'], true)) {
                    throw new RuntimeException("then.{$key}: key {$ak} is outside allowed_keys");
                }
            }
        }
    }

    public static function checkFrame(array $contractView, string $caseId, array $frames, array &$readKeys): void
    {
        $scopeWrites = $contractView['scope']['writes'] ?? [];
        $caseDef = $contractView['cases'][$caseId] ?? [];
        if (!array_key_exists('writes', $caseDef) || !is_array($caseDef['writes'])) {
            return;
        }
        $allowedCaseWrites = $caseDef['writes'];
        foreach ($scopeWrites as $res) {
            if (!in_array($res, $allowedCaseWrites, true)) {
                if (!array_key_exists($res, $frames)) {
                    continue;
                }
                $wCount = (int)($frames[$res]['writes'] ?? 0);
                if ($wCount !== 0) {
                    throw new RuntimeException("frame.violation:{$res}: expected 0 writes, observed {$wCount}");
                }
                $readKeys[] = "@frame:{$res}";
            } else {
                $readKeys[] = "@frame:{$res}";
            }
        }
    }

    public static function runProjectionChecks(array $contractView, string $caseId, array $observed, array $frames = []): array
    {
        $caseDef = $contractView['cases'][$caseId] ?? null;
        if (!is_array($caseDef)) {
            throw new RuntimeException("unknown case {$caseId}");
        }
        $thenTable = $caseDef['then'] ?? [];
        $projThen = $contractView['projections']['then'] ?? [];
        $readKeys = [];
        foreach ($thenTable as $key => $expected) {
            $ptr = $projThen[$key] ?? "/{$key}";
            [$present, $actual] = self::resolvePointer($observed, (string)$ptr);
            self::checkValue((string)$key, $actual, $expected, $present);
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
                'drift' => '0.4.0',
                'adapter' => self::VERSION,
                'policy' => 'core@1',
            ], $envMeta),
        ];
        file_put_contents($metaPath, json_encode($meta, JSON_UNESCAPED_SLASHES) . "\n");
    }
}
