package com.example.ordersystem.ordering.service;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.*;

@FeignClient(name = "product-service", url = "${PRODUCT_SERVICE_URL:http://product-service}")
public interface ProductFeign {
  record Request(Long productId, Integer quantity) {}

  record Result(String reservationId, String state, String productName, Integer unitPrice) {}

  @PutMapping("/product/internal/reservations/{id}")
  Result reserve(
      @PathVariable("id") String id,
      @RequestHeader("X-Internal-Token") String token,
      @RequestBody Request request);

  @PostMapping("/product/internal/reservations/{id}/confirm")
  Result confirm(@PathVariable("id") String id, @RequestHeader("X-Internal-Token") String token);

  @PostMapping("/product/internal/reservations/{id}/release")
  Result release(@PathVariable("id") String id, @RequestHeader("X-Internal-Token") String token);
}
