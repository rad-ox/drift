package drift;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.platform.engine.TestDescriptor;
import org.junit.platform.engine.TestSource;
import org.junit.platform.engine.UniqueId;
import org.junit.platform.engine.support.descriptor.AbstractTestDescriptor;
import org.junit.platform.engine.support.descriptor.ClassSource;
import org.junit.platform.engine.support.descriptor.MethodSource;

class DriftSelectTest {
    static class Sample {
        @DriftCase(contract = "c", cases = {"a", "b"}, level = "http")
        void tagged() {}

        @DriftCase(contract = "other", cases = "a", level = "http")
        void otherContract() {}

        void untagged() {}

        void untaggedSuffix() {}
    }

    @TempDir
    Path dir;

    @AfterEach
    void clear() {
        System.clearProperty(DriftSelect.SELECT);
    }

    private static TestDescriptor method(String name) throws Exception {
        return descriptor(MethodSource.from(Sample.class.getDeclaredMethod(name)));
    }

    private static TestDescriptor descriptor(TestSource source) {
        return new AbstractTestDescriptor(UniqueId.root("t", "x"), "x", source) {
            @Override
            public Type getType() {
                return Type.TEST;
            }
        };
    }

    private DriftSelect select(String... json) throws Exception {
        StringBuilder files = new StringBuilder();
        for (int i = 0; i < json.length; i++) {
            Path f = dir.resolve("s" + i + ".json");
            Files.writeString(f, json[i]);
            files.append(i == 0 ? "" : File.pathSeparator).append(f);
        }
        System.setProperty(DriftSelect.SELECT, files.toString());
        return new DriftSelect();
    }

    @Test
    void keepsEveryTestWithoutASelectionOrWhenItWidens() throws Exception {
        assertTrue(new DriftSelect().apply(method("untagged")).included());
        DriftSelect s = select("{\"all\": true, \"contract\": \"c\", \"cases\": [], \"tests\": []}");
        assertTrue(s.apply(method("untagged")).included());
    }

    @Test
    void keepsTaggedCasesAndSelectedTestsOnly() throws Exception {
        String sel = "{\"all\": false, \"contract\": \"c\", \"cases\": [{\"case\": \"b\", \"change\": \"changed\"}],"
                + " \"tests\": [\"drift.DriftSelectTest$Sample#untagged[1] x\"]}";
        DriftSelect s = select(sel);
        assertTrue(s.apply(method("tagged")).included());
        assertTrue(s.apply(method("untagged")).included());
        assertTrue(s.apply(method("untaggedSuffix")).excluded());
        assertTrue(s.apply(method("otherContract")).excluded());
        assertTrue(s.apply(descriptor(ClassSource.from(Sample.class))).included());
    }

    @Test
    void codeHitKeepsEveryTaggedTestOfTheContract() throws Exception {
        DriftSelect s = select("{\"all\": false, \"contract\": \"c\", \"code_hit\": true, \"cases\": [], \"tests\": []}");
        assertTrue(s.apply(method("tagged")).included());
        assertTrue(s.apply(method("otherContract")).excluded());
        assertTrue(s.apply(method("untagged")).excluded());
    }

    @Test
    void resourceHitKeepsEveryTaggedTestOfTheDependentContract() throws Exception {
        DriftSelect s = select("{\"all\": false, \"contract\": \"c\", \"resource_hit\": true, \"cases\": [], \"tests\": []}");
        assertTrue(s.apply(method("tagged")).included());
        assertTrue(s.apply(method("otherContract")).excluded());
        assertTrue(s.apply(method("untagged")).excluded());
        DriftSelect bounded = select("{\"all\": false, \"contract\": \"c\", \"resource_hit\": true,"
                + " \"replayed_cases\": [\"z\"], \"cases\": [], \"tests\": []}");
        assertTrue(bounded.apply(method("tagged")).excluded());
        DriftSelect boundedHit = select("{\"all\": false, \"contract\": \"c\", \"resource_hit\": true,"
                + " \"replayed_cases\": [\"b\"], \"cases\": [], \"tests\": []}");
        assertTrue(boundedHit.apply(method("tagged")).included());
    }

    @Test
    void joinsSeveralSelections() throws Exception {
        DriftSelect s = select("{\"all\": false, \"contract\": \"c\", \"cases\": [], \"tests\": []}",
                "{\"all\": false, \"contract\": \"other\", \"cases\": [{\"case\": \"a\", \"change\": \"added\"}],"
                        + " \"tests\": []}");
        assertTrue(s.apply(method("otherContract")).included());
        assertTrue(s.apply(method("tagged")).excluded());
    }

    @Test
    void failsOnAnUnreadableSelection() {
        System.setProperty(DriftSelect.SELECT, dir.resolve("absent.json").toString());
        assertThrows(RuntimeException.class, DriftSelect::new);
    }

    @Test
    void refusesReadsOutsideTheTagOfTheRunningTest() throws Exception {
        DriftCase tag = Sample.class.getDeclaredMethod("tagged").getAnnotation(DriftCase.class);
        try {
            Drift.begin(tag);
            assertThrows(IllegalStateException.class, () -> Drift.expect("c", "z"));
            assertThrows(IllegalStateException.class, () -> Drift.expect("other", "a"));
            Drift.begin(null);
            IllegalStateException e = assertThrows(IllegalStateException.class, () -> Drift.expect("c", "a"));
            assertTrue(e.getMessage().contains("no @DriftCase"), e.getMessage());
            Drift.end();
            // Outside a test the tag is not enforced: only the view lookup can fail.
            RuntimeException r = assertThrows(RuntimeException.class, () -> Drift.expect("c", "a"));
            assertTrue(r.getMessage().contains(Drift.RESOLVED) || r.getMessage().contains("c.json"),
                    r.getMessage());
        } finally {
            Drift.end();
        }
    }
}
