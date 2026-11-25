package drift;

import org.junit.jupiter.api.extension.*;

/** Fails a passing JUnit 5 {@link DriftCase} test when {@code strictWhen} finds unread {@code when.*} keys (D463). */
public final class DriftWhenExtension implements AfterTestExecutionCallback, InvocationInterceptor {
    private static void enforce(ExtensionContext ctx) {
        DriftCase tag = Drift.tag();
        if (tag == null) tag = ctx.getTestMethod().map(m -> m.getAnnotation(DriftCase.class)).orElse(null);
        DriftWhen.enforceAfterExecution(tag);
    }

    @Override
    public void afterTestExecution(ExtensionContext ctx) {
        if (ctx.getExecutionException().isEmpty()) enforce(ctx);
    }

    @Override
    public void interceptDynamicTest(Invocation<Void> inv, DynamicTestInvocationContext dctx, ExtensionContext ctx)
            throws Throwable {
        inv.proceed();
        enforce(ctx);
    }
}
