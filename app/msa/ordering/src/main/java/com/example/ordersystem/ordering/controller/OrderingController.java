package com.example.ordersystem.ordering.controller;

import com.example.ordersystem.ordering.domain.*;
import com.example.ordersystem.ordering.dto.OrderCreateDto;
import com.example.ordersystem.ordering.service.OrderingService;
import java.util.List;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/ordering")
public class OrderingController {
  public record View(
      Long id,
      Long productId,
      Integer quantity,
      String status,
      String productName,
      Integer unitPrice) {
    public static View of(Ordering o) {
      return new View(
          o.getId(),
          o.getProductId(),
          o.getQuantity(),
          o.getOrderStatus().name(),
          o.getProductName(),
          o.getUnitPrice());
    }
  }

  private final OrderingService service;

  public OrderingController(OrderingService service) {
    this.service = service;
  }

  @PostMapping("/create")
  public ResponseEntity<View> create(
      @jakarta.validation.Valid @RequestBody OrderCreateDto dto,
      @RequestHeader("X-User-Id") Long member,
      @RequestHeader("Idempotency-Key") String key) {
    var o = service.create(dto, member, key);
    HttpStatus status =
        o.getOrderStatus() == OrderStatus.ORDERED
            ? HttpStatus.CREATED
            : o.getOrderStatus() == OrderStatus.FAILED ? HttpStatus.CONFLICT : HttpStatus.ACCEPTED;
    return ResponseEntity.status(status).body(View.of(o));
  }

  @GetMapping("/{id}")
  public View detail(@PathVariable Long id, @RequestHeader("X-User-Id") Long member) {
    return View.of(service.owned(id, member));
  }

  @GetMapping("/mine")
  public List<View> mine(@RequestHeader("X-User-Id") Long member) {
    return service.mine(member).stream().map(View::of).toList();
  }
}
