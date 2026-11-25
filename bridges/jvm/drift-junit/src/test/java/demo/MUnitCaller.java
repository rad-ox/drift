package demo;

import drift.Drift;
import java.nio.file.Path;

/** Simulates a non-drift.* Scala 3 MUnit suite invoking closure lambdas on a worker thread. */
public final class MUnitCaller {
    public static void runLambda(Runnable body) {
        Runnable closure = () -> body.run();
        closure.run();
    }

    public static void runExpectVerify(String contract, String caseId, boolean selfStub, Path input, Object... entries) {
        Runnable lambda = () -> {
            Drift.Case c = Drift.expect(contract, caseId, "unit");
            if (selfStub) c.buildOutput();
            if (input != null) Drift.recordInput(input);
            c.verify(entries);
        };
        lambda.run();
    }

    public static void runAbandonedSelfStub(String contract, String caseId) {
        Runnable lambda = () -> {
            Drift.Case c = Drift.expect(contract, caseId, "unit");
            c.buildOutput();
        };
        lambda.run();
    }

    public static void runTwoStandaloneCasesSameMethod(String contract, String c1, String c2) {
        Drift.runCase(contract, c1, "unit", c -> {
            c.whenInt("x");
            c.verify("ok", true, "printed", "{}");
        });
        Drift.runCase(contract, c2, "unit", c -> {
            c.whenInt("x");
            c.verify("ok", true, "printed", "[]");
        });
    }
}
