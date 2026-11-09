package com.example.ordersystem.member.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import javax.net.ssl.*;

@Service
public class AdminDashboardService {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final HttpClient http;
    private static final String PROM = "http://monitoring-kube-prometheus-prometheus.monitoring.svc:9090";
    private static final Path SA = Path.of("/var/run/secrets/kubernetes.io/serviceaccount");

    @Autowired
    public AdminDashboardService(JdbcTemplate db, ObjectMapper json) {
        this(db, json, HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build());
    }
    // 테스트에서는 외부 호출을 모의 처리한다.
    AdminDashboardService(JdbcTemplate db, ObjectMapper json, HttpClient http) {
        this.db = db; this.json = json; this.http = http;
    }

    public Map<String, Object> summary() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("database", database());
        result.put("monitoring", monitoring());
        result.put("deployment", deployment());
        result.put("checkedAt", Instant.now().toString());
        return result;
    }

    private Map<String, Object> database() {
        try {
            // 기존 공용 DB의 집계값만 반환한다. 고객 정보나 비밀번호는 반환하지 않는다.
            return Map.of("status", "ok",
                    "members", db.queryForObject("select count(*) from member", Long.class),
                    "products", db.queryForObject("select count(*) from product", Long.class),
                    "orders", db.queryForObject("select count(*) from ordering", Long.class),
                    "stock", db.queryForObject("select coalesce(sum(stock_quantity), 0) from product", Long.class),
                    "tlsEncrypted", !Objects.toString(db.queryForObject(
                            "SELECT VARIABLE_VALUE FROM performance_schema.session_status WHERE VARIABLE_NAME = 'Ssl_cipher'",
                            String.class), "").isBlank());
        } catch (Exception e) { return Map.of("status", "unavailable"); }
    }

    private Map<String, Object> monitoring() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("grafana", "unavailable");
        result.put("metrics", "unavailable");
        try {
            JsonNode health = get(http, "http://monitoring-grafana.monitoring.svc/api/health", null);
            if ("ok".equals(health.path("database").asText())) result.put("grafana", "ok");
        } catch (Exception ignored) { /* 한 서비스 실패가 나머지 카드를 막지 않는다. */ }
        try {
            // Grafana가 시각화하는 원본 지표를 Prometheus에서 읽는다.
            double nodes = metric("sum(kube_node_status_condition{condition=\"Ready\",status=\"true\"})");
            double pods = metric("sum(kube_pod_status_ready{namespace=\"soldesk\",condition=\"true\"})");
            result.put("nodesReady", nodes);
            result.put("podsReady", pods);
            result.put("metrics", "ok");
        } catch (Exception ignored) { /* 수집되지 않은 값을 0으로 표시하지 않는다. */ }
        return result;
    }

    private double metric(String query) throws Exception {
        JsonNode response = get(http, PROM + "/api/v1/query?query="
                + URLEncoder.encode(query, StandardCharsets.UTF_8), null);
        JsonNode series = response.path("data").path("result");
        if (!"success".equals(response.path("status").asText()) || !series.isArray() || series.isEmpty()) {
            throw new IllegalStateException("Metric not available");
        }
        double value = Double.parseDouble(series.get(0).path("value").get(1).asText());
        if (!Double.isFinite(value)) throw new IllegalStateException("Metric not finite");
        return value;
    }

    private Map<String, Object> deployment() {
        try {
            // Pod의 CA로 API 서버를 검증한다. 인증서 검증을 끄지 않는다.
            var factory = CertificateFactory.getInstance("X.509");
            var trust = KeyStore.getInstance(KeyStore.getDefaultType());
            trust.load(null);
            try (var input = Files.newInputStream(SA.resolve("ca.crt"))) {
                trust.setCertificateEntry("cluster", factory.generateCertificate(input));
            }
            var managers = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
            managers.init(trust);
            var tls = SSLContext.getInstance("TLS");
            tls.init(null, managers.getTrustManagers(), null);
            var kube = HttpClient.newBuilder().sslContext(tls).connectTimeout(Duration.ofSeconds(2)).build();
            String token = Files.readString(SA.resolve("token")).trim();
            JsonNode app = get(kube, "https://kubernetes.default.svc/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/final-apps", token);
            return deploymentStatus(app);
        } catch (Exception e) { return Map.of("status", "unavailable"); }
    }

    static Map<String, Object> deploymentStatus(JsonNode app) {
        // Application 설정 전체 대신 화면에 필요한 상태만 공개한다.
        return Map.of("status", "ok", "sync", app.path("status").path("sync").path("status").asText("Unknown"),
                "health", app.path("status").path("health").path("status").asText("Unknown"),
                "revision", app.path("status").path("sync").path("revision").asText(""));
    }

    private JsonNode get(HttpClient client, String url, String token) throws Exception {
        var request = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(2)).GET();
        if (token != null) request.header("Authorization", "Bearer " + token);
        var response = client.send(request.build(), HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200) throw new IllegalStateException("Status unavailable");
        return json.readTree(response.body());
    }
}
