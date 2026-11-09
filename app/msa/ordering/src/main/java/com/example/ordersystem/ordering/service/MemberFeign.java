package com.example.ordersystem.ordering.service;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.*;

@FeignClient(name = "member-service", url = "${MEMBER_SERVICE_URL:http://member-service}")
public interface MemberFeign {
  record Email(String email) {}

  @GetMapping("/member/internal/{id}/email")
  Email email(@PathVariable("id") Long id, @RequestHeader("X-Internal-Token") String token);
}
