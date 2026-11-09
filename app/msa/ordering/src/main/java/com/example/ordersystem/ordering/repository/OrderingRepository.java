package com.example.ordersystem.ordering.repository;

import com.example.ordersystem.ordering.domain.*;
import jakarta.persistence.LockModeType;
import java.util.*;
import org.springframework.data.jpa.repository.*;
import org.springframework.data.repository.query.Param;

public interface OrderingRepository extends JpaRepository<Ordering, Long> {
  Optional<Ordering> findByMemberIdAndRequestKey(Long memberId, String requestKey);

  List<Ordering> findTop100ByMemberIdOrderByIdDesc(Long memberId);

  @Lock(LockModeType.PESSIMISTIC_WRITE)
  @Query("select o from Ordering o where o.id=:id")
  Optional<Ordering> locked(@Param("id") Long id);

  @Query(
      "select o.id from Ordering o where o.orderStatus in :states and (o.leaseUntil is null or"
          + " o.leaseUntil < :now) and (o.nextAttempt is null or o.nextAttempt <= :now) order by"
          + " o.id")
  List<Long> pending(
      @Param("states") List<OrderStatus> states,
      @Param("now") java.time.Instant now,
      org.springframework.data.domain.Pageable page);
}
