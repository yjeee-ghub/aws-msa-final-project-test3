package com.example.ordersystem.member.controller;

import com.example.ordersystem.member.service.AdminDashboardService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/member/admin")
public class AdminDashboardController {
    private final AdminDashboardService dashboard;
    public AdminDashboardController(AdminDashboardService dashboard) { this.dashboard = dashboard; }

    // Gateway의 서명 검증에 더해 컨트롤러에서도 관리자 권한을 검사한다.
    @GetMapping("/summary")
    public ResponseEntity<?> summary(@RequestHeader(value = "X-User-Role", required = false) String role) {
        if (!"ROLE_ADMIN".equals(role)) return ResponseEntity.status(403).build();
        return ResponseEntity.ok().header("Cache-Control", "no-store").body(dashboard.summary());
    }
}
