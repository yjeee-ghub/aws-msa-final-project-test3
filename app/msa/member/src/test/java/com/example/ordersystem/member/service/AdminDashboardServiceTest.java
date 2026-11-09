package com.example.ordersystem.member.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import java.net.http.*;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AdminDashboardServiceTest {
    @Test void returnsOnlyAggregateCountsAndUnavailableWhenSourcesCannotBeRead() throws Exception {
        var db = mock(JdbcTemplate.class);
        when(db.queryForObject("select count(*) from member", Long.class)).thenReturn(3L);
        when(db.queryForObject("select count(*) from product", Long.class)).thenReturn(5L);
        when(db.queryForObject("select count(*) from ordering", Long.class)).thenReturn(8L);
        when(db.queryForObject("select coalesce(sum(stock_quantity), 0) from product", Long.class)).thenReturn(27L);
        when(db.queryForObject("SELECT VARIABLE_VALUE FROM performance_schema.session_status WHERE VARIABLE_NAME = 'Ssl_cipher'", String.class)).thenReturn("TLS_AES_256_GCM_SHA384");
        var http = mock(HttpClient.class);
        when(http.send(any(), any(HttpResponse.BodyHandler.class))).thenThrow(new java.io.IOException("unavailable"));
        var result = new AdminDashboardService(db, new ObjectMapper(), http).summary();
        var counts = (Map<?, ?>) result.get("database");
        assertEquals(8L, counts.get("orders")); assertEquals(27L, counts.get("stock"));
        assertEquals(6, counts.size());
        assertEquals(true, counts.get("tlsEncrypted"));
        var monitoring = (Map<?, ?>) result.get("monitoring");
        assertEquals("unavailable", monitoring.get("metrics"));
        assertFalse(monitoring.containsKey("nodesReady"));
        assertEquals("unavailable", ((Map<?, ?>) result.get("deployment")).get("status"));
    }

    @Test void unencryptedDatabaseSessionIsNotReportedAsTls() {
        var db = mock(JdbcTemplate.class);
        when(db.queryForObject(anyString(), eq(Long.class))).thenReturn(0L);
        when(db.queryForObject(anyString(), eq(String.class))).thenReturn("");
        var result = new AdminDashboardService(db, new ObjectMapper(), mock(HttpClient.class)).summary();
        assertEquals(false, ((Map<?, ?>) result.get("database")).get("tlsEncrypted"));
    }

    @Test void databaseFailureDoesNotExposeSqlOrReturnFakeZero() {
        var db = mock(JdbcTemplate.class);
        when(db.queryForObject(anyString(), eq(Long.class))).thenThrow(new IllegalStateException("private DB detail"));
        var result = new AdminDashboardService(db, new ObjectMapper(), mock(HttpClient.class)).summary();
        assertEquals(Map.of("status", "unavailable"), result.get("database"));
    }

    @Test void applicationStatusDoesNotExposeApplicationSpec() throws Exception {
        var json = new ObjectMapper().readTree("""
            {"spec":{"source":{"repoURL":"private-source"}},
             "status":{"sync":{"status":"Synced","revision":"abcdef123456"},"health":{"status":"Healthy"}}}
            """);
        var status = AdminDashboardService.deploymentStatus(json);
        assertEquals("Synced", status.get("sync"));
        assertEquals("Healthy", status.get("health"));
        assertFalse(status.toString().contains("private-source"));
        assertEquals("Unknown", AdminDashboardService.deploymentStatus(new ObjectMapper().readTree("{}" )).get("health"));
    }
}
