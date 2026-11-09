package com.example.ordersystem.ordering.service;

import java.time.Instant;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OutboxTransactions {
  private final OutboxRepository events;

  public OutboxTransactions(OutboxRepository events) {
    this.events = events;
  }

  @Transactional
  public OutboxEvent claim(String id, String token) {
    var e = events.locked(id).orElseThrow();
    var now = Instant.now();
    if ("SENT".equals(e.status)
        || "FAILED".equals(e.status)
        || (e.nextAttempt != null && e.nextAttempt.isAfter(now))
        || ("SENDING".equals(e.status) && e.leaseUntil.isAfter(now))) return null;
    e.status = "SENDING";
    e.leaseToken = token;
    e.leaseUntil = now.plusSeconds(60);
    e.attempts++;
    return e;
  }

  @Transactional
  public void finish(String id, String token, boolean sent) {
    var e = events.locked(id).orElseThrow();
    if (!token.equals(e.leaseToken)) return;
    e.status = sent ? "SENT" : e.attempts >= 10 ? "FAILED" : "PENDING";
    e.nextAttempt =
        sent
            ? null
            : Instant.now().plusSeconds(Math.min(900, 5L * (1L << Math.min(8, e.attempts))));
    e.leaseToken = null;
    e.leaseUntil = null;
  }
}
