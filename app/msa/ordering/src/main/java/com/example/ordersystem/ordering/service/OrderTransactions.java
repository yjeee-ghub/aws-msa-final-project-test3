package com.example.ordersystem.ordering.service;

import com.example.ordersystem.ordering.domain.*;
import com.example.ordersystem.ordering.dto.OrderCreateDto;
import com.example.ordersystem.ordering.repository.OrderingRepository;
import java.time.Instant;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OrderTransactions {
  public static final List<OrderStatus> ACTIVE =
      List.of(OrderStatus.PENDING, OrderStatus.CONFIRMING, OrderStatus.COMPENSATING);
  private final OrderingRepository orders;
  private final OutboxRepository outbox;

  public OrderTransactions(OrderingRepository orders, OutboxRepository outbox) {
    this.orders = orders;
    this.outbox = outbox;
  }

  @Transactional
  public Ordering create(Long member, OrderCreateDto dto, String key, String reservation) {
    return orders.saveAndFlush(
        Ordering.builder()
            .memberId(member)
            .productId(dto.getProductId())
            .quantity(dto.getProductCount())
            .requestKey(key)
            .reservationId(reservation)
            .orderStatus(OrderStatus.PENDING)
            .build());
  }

  @Transactional
  public Ordering claim(Long id, String token) {
    var o = orders.locked(id).orElseThrow();
    var now = Instant.now();
    if (!ACTIVE.contains(o.getOrderStatus())
        || (o.getLeaseUntil() != null && o.getLeaseUntil().isAfter(now))
        || (o.getNextAttempt() != null && o.getNextAttempt().isAfter(now))) return null;
    o.claim(token, now.plusSeconds(90));
    return o;
  }

  private Ordering owned(Long id, String token) {
    var o = orders.locked(id).orElseThrow();
    if (!o.owns(token)) throw new IllegalStateException("Order lease expired");
    return o;
  }

  @Transactional
  public void prepare(Long id, String token, ProductFeign.Result product, String email) {
    if (email == null || !email.matches("[^\\s@]+@[^\\s@]+\\.[^\\s@]+"))
      throw new IllegalArgumentException("Invalid member email");
    owned(id, token).prepare(product.productName(), product.unitPrice(), email);
  }

  @Transactional
  public void compensate(Long id, String token) {
    owned(id, token).state(OrderStatus.COMPENSATING);
  }

  @Transactional
  public void fail(Long id, String token) {
    var o = owned(id, token);
    o.state(OrderStatus.FAILED);
    o.unlock();
  }

  @Transactional
  public void defer(Long id, String token) {
    owned(id, token).defer();
  }

  @Transactional
  public void complete(Long id, String token) {
    var o = owned(id, token);
    o.state(OrderStatus.ORDERED);
    outbox.save(new OutboxEvent(o));
    o.unlock();
  }
}
