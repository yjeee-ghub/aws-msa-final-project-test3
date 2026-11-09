package com.example.ordersystem.product.controller;

import com.example.ordersystem.product.service.ReservationService;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/product/internal/reservations")
public class ReservationController {
  private final ReservationService service;
  private final String token;

  public ReservationController(
      ReservationService service, @Value("${INTERNAL_SERVICE_TOKEN:}") String token) {
    this.service = service;
    this.token = token;
  }

  private void authorize(String supplied) {
    if (token.length() < 32
        || supplied == null
        || !MessageDigest.isEqual(
            token.getBytes(StandardCharsets.UTF_8), supplied.getBytes(StandardCharsets.UTF_8)))
      throw new ResponseStatusException(HttpStatus.FORBIDDEN);
  }

  @PutMapping("/{id}")
  public ReservationService.Result reserve(
      @PathVariable String id,
      @RequestHeader(value = "X-Internal-Token", required = false) String supplied,
      @RequestBody ReservationService.Request request) {
    authorize(supplied);
    return service.reserve(id, request);
  }

  @PostMapping("/{id}/confirm")
  public ReservationService.Result confirm(
      @PathVariable String id,
      @RequestHeader(value = "X-Internal-Token", required = false) String supplied) {
    authorize(supplied);
    return service.confirm(id);
  }

  @PostMapping("/{id}/release")
  public ReservationService.Result release(
      @PathVariable String id,
      @RequestHeader(value = "X-Internal-Token", required = false) String supplied) {
    authorize(supplied);
    return service.release(id);
  }
}
