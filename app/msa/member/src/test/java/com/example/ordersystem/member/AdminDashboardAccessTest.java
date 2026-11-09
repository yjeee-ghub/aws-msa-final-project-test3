package com.example.ordersystem.member;

import com.example.ordersystem.member.controller.AdminDashboardController;
import com.example.ordersystem.member.service.AdminDashboardService;
import org.junit.jupiter.api.Test;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AdminDashboardAccessTest {
    @Test void rejectsCustomersAndMissingRoleWithoutReadingData() {
        var service = mock(AdminDashboardService.class);
        var controller = new AdminDashboardController(service);
        assertEquals(403, controller.summary("ROLE_USER").getStatusCode().value());
        assertEquals(403, controller.summary(null).getStatusCode().value());
        verifyNoInteractions(service);
    }
    @Test void administratorResponseIsNotCached() {
        var service = mock(AdminDashboardService.class);
        when(service.summary()).thenReturn(Map.of("checkedAt", "now"));
        var response = new AdminDashboardController(service).summary("ROLE_ADMIN");
        assertEquals(200, response.getStatusCode().value());
        assertEquals("no-store", response.getHeaders().getFirst("Cache-Control"));
    }
}
