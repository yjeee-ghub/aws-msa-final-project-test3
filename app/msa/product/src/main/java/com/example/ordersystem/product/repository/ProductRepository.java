package com.example.ordersystem.product.repository;

import com.example.ordersystem.product.domain.Product;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface ProductRepository extends JpaRepository<Product, Long> {
    List<Product> findAllByOrderByIdDesc();

    // 동시 주문에서 같은 재고를 중복 차감하지 않도록 행 잠금을 건다.
    @org.springframework.data.jpa.repository.Lock(jakarta.persistence.LockModeType.PESSIMISTIC_WRITE)
    @org.springframework.data.jpa.repository.Query("select p from Product p where p.id = :id")
    java.util.Optional<Product> findForStockUpdate(@org.springframework.data.repository.query.Param("id") Long id);
}
