package ai.caseintel.api.agent;

import ai.caseintel.api.config.AppProperties;
import com.fasterxml.jackson.databind.JsonNode;
import java.nio.file.Path;
import java.time.Duration;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.MediaType;
import org.springframework.http.client.BufferingClientHttpRequestFactory;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

@Component
public class AgentClient {

    private final RestClient client;
    private final RestClient healthClient;

    public AgentClient(AppProperties props, RestClient.Builder builder) {
        AppProperties.Agent agent = props.agent();
        this.client = builder.clone()
                .baseUrl(agent.baseUrl())
                .requestFactory(new BufferingClientHttpRequestFactory(factory(agent.connectTimeout(), agent.readTimeout())))
                .build();
        this.healthClient = builder.clone()
                .baseUrl(agent.baseUrl())
                .requestFactory(factory(agent.healthTimeout(), agent.healthTimeout()))
                .build();
    }

    private static SimpleClientHttpRequestFactory factory(Duration connect, Duration read) {
        SimpleClientHttpRequestFactory f = new SimpleClientHttpRequestFactory();
        f.setConnectTimeout(connect);
        f.setReadTimeout(read);
        return f;
    }

    public JsonNode extract(Path file, String filename, String schema) {
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("file", new FileSystemResource(file) {
            @Override
            public String getFilename() {
                return filename;
            }
        });
        body.add("schema", schema);
        return call(() -> client.post()
                .uri("/v1/extract")
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .body(body)
                .retrieve()
                .body(JsonNode.class), "extract");
    }

    public JsonNode explain(JsonNode request) {
        return call(() -> client.post()
                .uri("/v1/explain")
                .contentType(MediaType.APPLICATION_JSON)
                .body(request)
                .retrieve()
                .body(JsonNode.class), "explain");
    }

    public boolean healthy() {
        try {
            healthClient.get().uri("/health").retrieve().toBodilessEntity();
            return true;
        } catch (RestClientException e) {
            return false;
        }
    }

    private static JsonNode call(java.util.function.Supplier<JsonNode> request, String op) {
        try {
            JsonNode res = request.get();
            if (res == null) {
                throw new AgentException("Agent " + op + " returned an empty body");
            }
            return res;
        } catch (RestClientException e) {
            throw new AgentException("Agent " + op + " failed: " + e.getMessage(), e);
        }
    }
}
