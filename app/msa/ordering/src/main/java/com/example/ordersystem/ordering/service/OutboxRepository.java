package com.example.ordersystem.ordering.service;

import jakarta.persistence.LockModeType;
import java.time.Instant;
import java.util.*;
import org.springframework.data.jpa.repository.*;
import org.springframework.data.repository.query.Param;

public interface OutboxRepository extends JpaRepository<OutboxEvent, String> {
  @Lock(LockModeType.PESSIMISTIC_WRITE)
  @Query("select e from OutboxEvent e where e.id=:id")
  Optional<OutboxEvent> locked(@Param("id") String id);

  @Query(
      "select e.id from OutboxEvent e where (e.status='PENDING' or (e.status='SENDING' and"
          + " e.leaseUntil<:now)) and (e.nextAttempt is null or e.nextAttempt<=:now) order by"
          + " e.createdAt")
  List<String> due(@Param("now") Instant now, org.springframework.data.domain.Pageable page);
}
