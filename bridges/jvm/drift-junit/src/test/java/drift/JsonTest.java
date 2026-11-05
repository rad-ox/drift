package drift;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class JsonTest {
    @Test
    void parsesTheResolvedViewSubset() {
        Object v = Json.parse("{\"a\": [1, -2.5, \"x\\u0041\\n\"], \"b\": {\"t\": true, \"n\": null}}");
        assertEquals(Map.of("a", List.of(1L, -2.5, "xA\n"), "b", java.util.Collections.unmodifiableMap(
                new java.util.LinkedHashMap<>() {{ put("t", true); put("n", null); }})), v);
    }

    @Test
    void refusesTrailingContentAndBadInput() {
        assertThrows(IllegalArgumentException.class, () -> Json.parse("{} x"));
        assertThrows(IllegalArgumentException.class, () -> Json.parse("{\"a\" 1}"));
        assertThrows(IllegalArgumentException.class, () -> Json.parse("\"open"));
    }

    @Test
    void decodesWhatShellsWrite() {
        String text = "{\"k\": \"\u00e8\"}";
        byte[] utf8 = text.getBytes(StandardCharsets.UTF_8);
        byte[] bom = concat(new byte[] {(byte) 0xef, (byte) 0xbb, (byte) 0xbf}, utf8);
        byte[] le = concat(new byte[] {(byte) 0xff, (byte) 0xfe}, text.getBytes(StandardCharsets.UTF_16LE));
        byte[] be = concat(new byte[] {(byte) 0xfe, (byte) 0xff}, text.getBytes(StandardCharsets.UTF_16BE));
        for (byte[] b : List.of(utf8, bom, le, be)) {
            assertEquals(Map.of("k", "\u00e8"), Json.parse(Json.decode(b)));
        }
    }

    private static byte[] concat(byte[] a, byte[] b) {
        byte[] r = java.util.Arrays.copyOf(a, a.length + b.length);
        System.arraycopy(b, 0, r, a.length, b.length);
        return r;
    }

    @Test
    void writesEscapedFields() {
        StringBuilder b = new StringBuilder();
        Json.field(b, "k", "a\"b\\c\u0001").append(',');
        Json.field(b, "l", List.of("x", "y"));
        assertEquals("\"k\":\"a\\\"b\\\\c\\u0001\",\"l\":[\"x\",\"y\"]", b.toString());
    }
}
