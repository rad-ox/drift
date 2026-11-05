package example.items;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/** A synthetic read-only HTTP service: GET /items/{id}. */
public final class ItemServer implements AutoCloseable {
    private final Map<Long, String> items;
    private final HttpServer server;

    public ItemServer(Map<Long, String> items) throws IOException {
        this.items = Map.copyOf(items);
        this.server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/items/", this::handle);
        server.start();
    }

    public int port() {
        return server.getAddress().getPort();
    }

    /** The answer to one request, independent of HTTP. */
    public Reply get(String id) {
        long n;
        try {
            n = Long.parseLong(id);
        } catch (NumberFormatException e) {
            n = -1;
        }
        if (n <= 0) {
            return new Reply(400, "{\"error\":\"id must be a positive integer\"}");
        }
        String name = items.get(n);
        if (name == null) {
            return new Reply(404, "{\"error\":\"item not found\"}");
        }
        return new Reply(200, "{\"id\":" + n + ",\"name\":\"" + name + "\"}");
    }

    private void handle(HttpExchange ex) throws IOException {
        Reply r = "GET".equals(ex.getRequestMethod())
                ? get(ex.getRequestURI().getPath().substring("/items/".length()))
                : new Reply(405, "{\"error\":\"method not allowed\"}");
        byte[] body = r.body().getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json");
        ex.sendResponseHeaders(r.status(), body.length);
        try (OutputStream out = ex.getResponseBody()) {
            out.write(body);
        }
    }

    @Override
    public void close() {
        server.stop(0);
    }

    public record Reply(int status, String body) {}
}
