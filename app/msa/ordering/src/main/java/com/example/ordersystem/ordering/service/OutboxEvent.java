package com.example.ordersystem.ordering.service;

import com.example.ordersystem.ordering.domain.Ordering;
import jakarta.persistence.*;
import java.time.Instant;

@Entity
@Table(name = "order_outbox", uniqueConstraints = @UniqueConstraint(columnNames = "orderId"))
public class OutboxEvent {
  @Id String id;
  Long orderId;
  Long memberId;
  String recipientEmail;
  String productName;
  Integer quantity;
  Long total;
  String status;
  String leaseToken;
  Instant leaseUntil;
  Instant nextAttempt;
  int attempts;
  Instant createdAt;

  protected OutboxEvent() {}

  OutboxEvent(Ordering order) {
    id = java.util.UUID.randomUUID().toString();
    orderId = order.getId();
    memberId = order.getMemberId();
    recipientEmail = order.getRecipientEmail();
    productName = order.getProductName();
    quantity = order.getQuantity();
    total = (long) order.getUnitPrice() * quantity;
    status = "PENDING";
    createdAt = Instant.now();
  }
}
