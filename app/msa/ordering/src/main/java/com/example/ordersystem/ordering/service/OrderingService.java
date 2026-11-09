package com.example.ordersystem.ordering.service;

import com.example.ordersystem.ordering.domain.*;
import com.example.ordersystem.ordering.dto.OrderCreateDto;
import com.example.ordersystem.ordering.repository.OrderingRepository;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class OrderingService {
  private static final org.slf4j.Logger log =
      org.slf4j.LoggerFactory.getLogger(OrderingService.class);
  private final OrderingRepository orders;
  private final OrderTransactions tx;
  private final ProductFeign product;
  private final MemberFeign member;
  private final String token;

  public OrderingService(
      OrderingRepository orders,
      OrderTransactions tx,
      ProductFeign product,
      MemberFeign member,
      @Value("${INTERNAL_SERVICE_TOKEN:}") String token) {
    this.orders = orders;
    this.tx = tx;
    this.product = product;
    this.member = member;
    this.token = token;
  }

  public Ordering create(OrderCreateDto dto, Long memberId, String key) {
    if (memberId == null || memberId < 1)
      throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
    if (key == null || !key.matches("[A-Za-z0-9_-]{16,80}"))
      throw new ResponseStatusException(
          HttpStatus.BAD_REQUEST, "Idempotency-Key (16-80 characters) required");
    Ordering o = orders.findByMemberIdAndRequestKey(memberId, key).orElse(null);
    if (o == null) {
      try {
        o = tx.create(memberId, dto, key, reservation(memberId, key));
      } catch (DataIntegrityViolationException concurrent) {
        o = orders.findByMemberIdAndRequestKey(memberId, key).orElseThrow(() -> concurrent);
      }
    }
    if (!dto.getProductId().equals(o.getProductId())
        || !dto.getProductCount().equals(o.getQuantity()))
      throw new ResponseStatusException(
          HttpStatus.CONFLICT, "Request key already used for another order");
    process(o.getId());
    return orders.findById(o.getId()).orElseThrow();
  }

  private String reservation(Long member, String key) {
    try {
      return HexFormat.of()
          .formatHex(
              MessageDigest.getInstance("SHA-256")
                  .digest((member + ":" + key).getBytes(StandardCharsets.UTF_8)));
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
  }

  // 네트워크 호출은 DB 트랜잭션 밖에서 수행하고, 각 단계의 의도를 먼저 저장한다.
  public void process(Long id) {
    String lease = UUID.randomUUID().toString();
    Ordering o = tx.claim(id, lease);
    if (o == null) return;
    try {
      if (o.getOrderStatus() == OrderStatus.PENDING) {
        try {
          var reserved =
              product.reserve(
                  o.getReservationId(),
                  token,
                  new ProductFeign.Request(o.getProductId(), o.getQuantity()));
          var recipient = member.email(o.getMemberId(), token);
          tx.prepare(id, lease, reserved, recipient.email());
        } catch (Exception failure) {
          tx.compensate(id, lease); // 확보 응답이 유실됐어도 release tombstone으로 지연 요청을 막는다.
          product.release(o.getReservationId(), token);
          tx.fail(id, lease);
          return;
        }
      }
      if (o.getOrderStatus() == OrderStatus.COMPENSATING) {
        product.release(o.getReservationId(), token);
        tx.fail(id, lease);
        return;
      }
      product.confirm(o.getReservationId(), token);
      // confirm 응답 유실/DB 실패는 CONFIRMING에서 재개한다. 확정 재고를 임의로 해제하지 않는다.
      tx.complete(id, lease);
    } catch (Exception retry) {
      log.warn("Order {} awaiting recovery ({})", id, retry.getClass().getSimpleName());
      try {
        tx.defer(id, lease);
      } catch (Exception unavailable) {
        /* 임대 만료 후 재개 */
      }
    }
  }

  @Scheduled(
      fixedDelayString = "${orders.recovery-ms:5000}",
      initialDelayString = "${orders.initial-delay-ms:5000}")
  public void recover() {
    for (Long id : orders.pending(OrderTransactions.ACTIVE, Instant.now(), PageRequest.of(0, 20)))
      try {
        process(id);
      } catch (Exception unavailable) {
        log.warn("Order {} recovery delayed ({})", id, unavailable.getClass().getSimpleName());
        /* 다음 순회에서 다시 확인 */
      }
  }

  public Ordering owned(Long id, Long member) {
    return orders
        .findById(id)
        .filter(o -> o.getMemberId().equals(member))
        .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
  }

  public List<Ordering> mine(Long member) {
    return orders.findTop100ByMemberIdOrderByIdDesc(member);
  }
}
