package example.items;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import drift.Drift;
import drift.DriftCase;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.Map;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

class ItemGetTest {
    private static final Map<Long, String> ITEMS = Map.of(1L, "lamp", 2L, "desk");
    private static ItemServer server;
    private static final HttpClient HTTP = HttpClient.newHttpClient();

    @BeforeAll
    static void start() throws Exception {
        server = new ItemServer(ITEMS);
    }

    @AfterAll
    static void stop() {
        server.close();
    }

    private HttpResponse<String> send(String request) throws Exception {
        String[] parts = request.split(" ", 2);
        HttpRequest req = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + server.port() + parts[1]))
                .method(parts[0], HttpRequest.BodyPublishers.noBody())
                .build();
        return HTTP.send(req, HttpResponse.BodyHandlers.ofString());
    }

    @Test
    @DriftCase(contract = "item-get", cases = "found", level = "http")
    void returnsAnExistingItem() throws Exception {
        Drift.Case c = Drift.expect("item-get", "found");
        HttpResponse<String> r = send(c.whenString("request"));
        assertEquals(c.thenInt("status"), r.statusCode());
        assertTrue(r.body().contains("\"name\":\"" + c.thenString("name") + "\""), r.body());
    }

    @Test
    @DriftCase(contract = "item-get", cases = "not-found", level = "http")
    void answersNotFoundForAnUnknownId() throws Exception {
        Drift.Case c = Drift.expect("item-get", "not-found");
        HttpResponse<String> r = send(c.whenString("request"));
        assertEquals(c.thenInt("status"), r.statusCode());
        assertTrue(r.body().contains("\"error\":\"" + c.thenString("error") + "\""), r.body());
    }

    @Test
    @DriftCase(contract = "item-get", cases = "bad-id", level = "http")
    void refusesAnIdThatIsNotAPositiveInteger() throws Exception {
        Drift.Case c = Drift.expect("item-get", "bad-id");
        HttpResponse<String> r = send(c.whenString("request"));
        assertEquals(c.thenInt("status"), r.statusCode());
        assertTrue(r.body().contains("\"error\":\"" + c.thenString("error") + "\""), r.body());
    }

    @Test
    @DriftCase(contract = "item-get", cases = "read-only", level = "unit")
    void readingLeavesTheItemsUnchanged() {
        Drift.Case c = Drift.expect("item-get", "read-only");
        String id = c.whenString("request").substring("GET /items/".length());
        Map<Long, String> before = Map.copyOf(ITEMS);
        assertEquals(c.thenInt("status"), server.get(id).status());
        assertEquals(before, ITEMS);
    }
}
