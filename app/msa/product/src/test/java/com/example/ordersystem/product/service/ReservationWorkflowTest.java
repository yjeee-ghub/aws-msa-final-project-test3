package com.example.ordersystem.product.service;

import static org.junit.jupiter.api.Assertions.*;

import com.example.ordersystem.product.domain.Product;
import com.example.ordersystem.product.dto.ProductEditDto;
import com.example.ordersystem.product.repository.ProductRepository;
import jakarta.persistence.EntityNotFoundException;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.*;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

@DataJpaTest(showSql = false)
@ActiveProfiles("test")
@Import({ReservationService.class, ProductService.class})
@Transactional(propagation = Propagation.NOT_SUPPORTED)
class ReservationWorkflowTest {
  @Autowired ReservationService service;
  @Autowired ProductService catalog;
  @Autowired ProductRepository products;
  @MockBean S3Service s3;

  Long product(int stock) {
    return products
        .saveAndFlush(
            Product.builder().name("shoe").price(1500).memberId(1L).stockQuantity(stock).build())
        .getId();
  }

  String key(char c) {
    return String.valueOf(c).repeat(64);
  }

  @Test
  void repeatedReserveAndReleaseOnlyChangeStockOnce() {
    Long id = product(5);
    String key = key('a');
    service.reserve(key, new ReservationService.Request(id, 2));
    service.reserve(key, new ReservationService.Request(id, 2));
    assertEquals(3, products.findById(id).orElseThrow().getStockQuantity());
    service.release(key);
    service.release(key);
    assertEquals(5, products.findById(id).orElseThrow().getStockQuantity());
    assertThrows(
        Exception.class, () -> service.reserve(key, new ReservationService.Request(id, 2)));
  }

  @Test
  void releaseBeforeDelayedReserveIsATombstone() {
    String key = key('b');
    service.release(key);
    Long id = product(2);
    assertThrows(
        Exception.class, () -> service.reserve(key, new ReservationService.Request(id, 1)));
    assertEquals(2, products.findById(id).orElseThrow().getStockQuantity());
  }

  @Test
  void confirmedReservationCannotBeReleased() {
    String key = key('c');
    Long id = product(2);
    service.reserve(key, new ReservationService.Request(id, 1));
    service.confirm(key);
    service.confirm(key);
    assertThrows(Exception.class, () -> service.release(key));
    assertEquals(1, products.findById(id).orElseThrow().getStockQuantity());
  }

  @Test
  void changedPayloadIsRejected() {
    String key = key('d');
    Long id = product(5);
    service.reserve(key, new ReservationService.Request(id, 1));
    assertThrows(
        Exception.class, () -> service.reserve(key, new ReservationService.Request(id, 2)));
    assertEquals(4, products.findById(id).orElseThrow().getStockQuantity());
  }

  @Test
  void deletingHidesProductAndKeepsExistingReservationCompensation() {
    Long id = product(5);
    String reservation = key('1');
    service.reserve(reservation, new ReservationService.Request(id, 2));

    catalog.productDelete(id);
    catalog.productDelete(id);

    assertTrue(catalog.productList().stream().noneMatch(product -> id.equals(product.getId())));
    assertThrows(EntityNotFoundException.class, () -> catalog.productDetail(id));
    var missing = assertThrows(ResponseStatusException.class,
        () -> service.reserve(key('2'), new ReservationService.Request(id, 1)));
    assertEquals(HttpStatus.NOT_FOUND, missing.getStatusCode());
    service.release(reservation);
    assertEquals(5, products.findById(id).orElseThrow().getStockQuantity());
  }

  @Test
  void editingCannotOverwriteConcurrentStockChanges() throws Exception {
    Long id = products.saveAndFlush(Product.builder().name("flower").price(1500).memberId(1L)
        .imageUrl("https://example.test/flower.jpg").stockQuantity(5).build()).getId();
    service.reserve(key('3'), new ReservationService.Request(id, 2));
    var edit = new ProductEditDto();
    edit.setName("Flower bouquet");
    edit.setPrice(2000);
    edit.setExpectedStockQuantity(5);
    edit.setStockQuantity(10);

    var conflict = assertThrows(ResponseStatusException.class, () -> catalog.productEdit(id, edit));
    assertEquals(HttpStatus.CONFLICT, conflict.getStatusCode());
    assertEquals("flower", catalog.productDetail(id).getName());

    edit.setStockQuantity(null);
    var updated = catalog.productEdit(id, edit);
    assertEquals("Flower bouquet", updated.getName());
    assertEquals(3, updated.getStockQuantity());
    assertEquals("https://example.test/flower.jpg", updated.getImageUrl());

    edit.setExpectedStockQuantity(3);
    edit.setStockQuantity(10);
    assertEquals(10, catalog.productEdit(id, edit).getStockQuantity());
  }

  @Test
  void concurrentReservationsCannotOversellLastUnit() throws Exception {
    Long id = product(1);
    var gate = new CountDownLatch(1);
    var pool = Executors.newFixedThreadPool(2);
    try {
      var a = pool.submit(() -> reserve(gate, key('e'), id));
      var b = pool.submit(() -> reserve(gate, key('f'), id));
      gate.countDown();
      assertEquals(
          1, (a.get(15, TimeUnit.SECONDS) ? 1 : 0) + (b.get(15, TimeUnit.SECONDS) ? 1 : 0));
      assertEquals(0, products.findById(id).orElseThrow().getStockQuantity());
    } finally {
      pool.shutdownNow();
    }
  }

  boolean reserve(CountDownLatch gate, String key, Long id) throws Exception {
    gate.await();
    try {
      service.reserve(key, new ReservationService.Request(id, 1));
      return true;
    } catch (IllegalArgumentException expected) {
      return false;
    }
  }
}
