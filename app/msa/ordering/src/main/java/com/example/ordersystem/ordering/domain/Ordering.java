package com.example.ordersystem.ordering.domain;

import com.example.ordersystem.common.domain.BaseTimeEntity;
import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Entity
@Table(
    uniqueConstraints =
        @UniqueConstraint(
            name = "uk_order_member_request",
            columnNames = {"member_id", "request_key"}))
@NoArgsConstructor
@AllArgsConstructor
@Builder
@Getter
public class Ordering extends BaseTimeEntity {
  @Id
  @GeneratedValue(strategy = GenerationType.IDENTITY)
  private Long id;

  @Column(nullable = false, name = "member_id")
  private Long memberId;

  @Column(nullable = false)
  private Long productId;

  @Column(nullable = false)
  private Integer quantity;

  @Column(name = "request_key", length = 80)
  private String requestKey;

  private String reservationId;
  private String productName;
  private Integer unitPrice;
  private String recipientEmail;
  private String leaseToken;
  private java.time.Instant leaseUntil;
  private java.time.Instant nextAttempt;
  @Builder.Default private int attempts = 0;

  public void claim(String token, java.time.Instant until) {
    leaseToken = token;
    leaseUntil = until;
    attempts++;
  }

  public boolean owns(String token) {
    return java.util.Objects.equals(token, leaseToken);
  }

  public void prepare(String name, int price, String email) {
    productName = name;
    unitPrice = price;
    recipientEmail = email;
    orderStatus = OrderStatus.CONFIRMING;
  }

  public void state(OrderStatus status) {
    orderStatus = status;
  }

  public void defer() {
    leaseToken = null;
    leaseUntil = null;
    nextAttempt = java.time.Instant.now().plusSeconds(Math.min(300, 5L * Math.max(1, attempts)));
  }

  public void unlock() {
    leaseToken = null;
    leaseUntil = null;
    nextAttempt = null;
  }

  @org.hibernate.annotations.JdbcTypeCode(org.hibernate.type.SqlTypes.VARCHAR)
  @Column(length = 32)
  @Enumerated(EnumType.STRING)
  @Builder.Default
  private OrderStatus orderStatus = OrderStatus.ORDERED;
}
