package com.example.ordersystem.product.service;

import com.example.ordersystem.product.repository.ProductRepository;
import jakarta.persistence.*;
import java.util.Optional;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

@Entity
@Table(name = "stock_reservation")
class StockReservation {
  @Id
  @Column(length = 64)
  String id;

  Long productId;
  Integer quantity;
  String state;
  String productName;
  Integer unitPrice;

  protected StockReservation() {}

  StockReservation(String id) {
    this.id = id;
    this.state = "NEW";
  }
}

interface ReservationRepository extends JpaRepository<StockReservation, String> {
  @Lock(LockModeType.PESSIMISTIC_WRITE)
  @Query("select r from StockReservation r where r.id=:id")
  Optional<StockReservation> locked(@Param("id") String id);
}

@Service
public class ReservationService {
  public record Request(Long productId, Integer quantity) {}

  public record Result(String reservationId, String state, String productName, Integer unitPrice) {}

  private final ReservationRepository reservations;
  private final ProductRepository products;
  private final TransactionTemplate tx;

  public ReservationService(
      ReservationRepository reservations,
      ProductRepository products,
      PlatformTransactionManager manager) {
    this.reservations = reservations;
    this.products = products;
    this.tx = new TransactionTemplate(manager);
  }

  private void ensure(String id) {
    if (id == null || !id.matches("[a-f0-9]{64}"))
      throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid reservation ID");
    // 유일 키 충돌은 트랜잭션 밖에서 처리하여 rollback-only 상태를 재사용하지 않는다.
    try {
      tx.executeWithoutResult(
          s -> {
            if (!reservations.existsById(id)) reservations.saveAndFlush(new StockReservation(id));
          });
    } catch (DataIntegrityViolationException conflict) {
      if (!reservations.existsById(id)) throw conflict;
    }
  }

  public Result reserve(String id, Request request) {
    if (request == null
        || request.productId() == null
        || request.productId() < 1
        || request.quantity() == null
        || request.quantity() < 1
        || request.quantity() > 999)
      throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid stock request");
    ensure(id);
    return tx.execute(
        s -> {
          var r = reservations.locked(id).orElseThrow();
          if ("RELEASED".equals(r.state))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Reservation already released");
          if (!"NEW".equals(r.state)) {
            if (!request.productId().equals(r.productId) || !request.quantity().equals(r.quantity))
              throw new ResponseStatusException(HttpStatus.CONFLICT, "Reservation payload changed");
            return view(r);
          }
          var p =
              products
                  .findForStockUpdate(request.productId())
                  .orElseThrow(
                      () -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Product not found"));
          p.updateStockQuantity(request.quantity());
          r.productId = p.getId();
          r.quantity = request.quantity();
          r.productName = p.getName();
          r.unitPrice = p.getPrice();
          r.state = "RESERVED";
          return view(r);
        });
  }

  public Result confirm(String id) {
    ensure(id);
    return tx.execute(
        s -> {
          var r = reservations.locked(id).orElseThrow();
          if (!"RESERVED".equals(r.state) && !"CONFIRMED".equals(r.state))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Reservation is not available");
          r.state = "CONFIRMED";
          return view(r);
        });
  }

  public Result release(String id) {
    ensure(id);
    return tx.execute(
        s -> {
          var r = reservations.locked(id).orElseThrow();
          if ("CONFIRMED".equals(r.state))
            throw new ResponseStatusException(
                HttpStatus.CONFLICT, "Confirmed stock cannot be released");
          if ("RESERVED".equals(r.state))
            products.findForStockUpdate(r.productId).orElseThrow().restoreStock(r.quantity);
          r.state = "RELEASED";
          return view(r);
        });
  }

  private Result view(StockReservation r) {
    return new Result(r.id, r.state, r.productName, r.unitPrice);
  }
}
