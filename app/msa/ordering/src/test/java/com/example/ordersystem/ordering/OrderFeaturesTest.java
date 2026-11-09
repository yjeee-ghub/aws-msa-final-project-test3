package com.example.ordersystem.ordering;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.example.ordersystem.ordering.domain.*;
import com.example.ordersystem.ordering.dto.OrderCreateDto;
import com.example.ordersystem.ordering.repository.OrderingRepository;
import com.example.ordersystem.ordering.service.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import software.amazon.awssdk.services.sns.SnsClient;
import software.amazon.awssdk.services.sns.model.PublishRequest;

@SpringBootTest
@ActiveProfiles("test")
class OrderFeaturesTest {
  @Autowired OrderingService service;
  @Autowired OrderingRepository orders;
  @Autowired OutboxRepository events;
  @Autowired OutboxTransactions outbox;
  @Autowired JdbcTemplate jdbc;
  @SpyBean OrderTransactions transactions;
  @MockBean ProductFeign product;
  @MockBean MemberFeign member;

  @BeforeEach
  void clean() {
    events.deleteAll();
    orders.deleteAll();
    reset(product, member, transactions);
    when(product.reserve(anyString(), anyString(), any()))
        .thenAnswer(i -> new ProductFeign.Result(i.getArgument(0), "RESERVED", "shoe", 1500));
    when(member.email(anyLong(), anyString()))
        .thenReturn(new MemberFeign.Email("test@example.com"));
  }

  OrderCreateDto dto() {
    return new OrderCreateDto(1L, 2);
  }

  void retry(Long id) {
    jdbc.update("update ordering set next_attempt=null,lease_until=null where id=?", id);
    service.process(id);
  }

  @Test
  void sameRequestReturnsSameOrderAndOneOutbox() {
    var a = service.create(dto(), 7L, "request-key-00001");
    var b = service.create(dto(), 7L, "request-key-00001");
    assertEquals(a.getId(), b.getId());
    assertEquals(OrderStatus.ORDERED, b.getOrderStatus());
    assertEquals(1, orders.count());
    assertEquals(1, events.count());
    assertEquals("shoe", b.getProductName());
    verify(product, times(1)).reserve(anyString(), anyString(), any());
    assertThrows(
        org.springframework.web.server.ResponseStatusException.class,
        () -> service.create(new OrderCreateDto(1L, 3), 7L, "request-key-00001"));
  }

  @Test
  void failedMemberLookupCompensatesReservedStock() {
    when(member.email(anyLong(), anyString())).thenThrow(new RuntimeException("unavailable"));
    var o = service.create(dto(), 7L, "request-key-00002");
    assertEquals(OrderStatus.FAILED, o.getOrderStatus());
    assertEquals(0, events.count());
    verify(product).release(eq(o.getReservationId()), anyString());
    verify(product, never()).confirm(anyString(), anyString());
  }

  @Test
  void reservationResponseLossStillCreatesReleaseIntent() {
    when(product.reserve(anyString(), anyString(), any()))
        .thenThrow(new RuntimeException("response lost after commit"));
    var o = service.create(dto(), 7L, "request-key-00003");
    assertEquals(OrderStatus.FAILED, o.getOrderStatus());
    verify(product).release(eq(o.getReservationId()), anyString());
  }

  @Test
  void compensationFailureIsDurableAndRecoveryDoesNotReserveAgain() {
    when(member.email(anyLong(), anyString()))
        .thenThrow(new RuntimeException("member unavailable"));
    when(product.release(anyString(), anyString()))
        .thenThrow(new RuntimeException("release unavailable"))
        .thenReturn(null);
    var o = service.create(dto(), 7L, "request-key-00004");
    assertEquals(OrderStatus.COMPENSATING, o.getOrderStatus());
    retry(o.getId());
    assertEquals(OrderStatus.FAILED, orders.findById(o.getId()).orElseThrow().getOrderStatus());
    verify(product, times(1)).reserve(anyString(), anyString(), any());
  }

  @Test
  void lostConfirmResponseRetriesConfirmationAndPublishesOnce() {
    when(product.confirm(anyString(), anyString()))
        .thenThrow(new RuntimeException("confirm response lost"))
        .thenReturn(null);
    var o = service.create(dto(), 7L, "request-key-00005");
    assertEquals(OrderStatus.CONFIRMING, o.getOrderStatus());
    assertEquals(0, events.count());
    retry(o.getId());
    assertEquals(OrderStatus.ORDERED, orders.findById(o.getId()).orElseThrow().getOrderStatus());
    assertEquals(1, events.count());
    verify(product, times(1)).reserve(anyString(), anyString(), any());
    verify(product, never()).release(anyString(), anyString());
  }

  @Test
  void orderSaveFailureAfterReserveTriggersCompensation() {
    doThrow(new RuntimeException("local DB save failure"))
        .when(transactions)
        .prepare(anyLong(), anyString(), any(), anyString());
    var o = service.create(dto(), 7L, "request-key-00006");
    assertEquals(OrderStatus.FAILED, o.getOrderStatus());
    verify(product).release(eq(o.getReservationId()), anyString());
    assertEquals(0, events.count());
  }

  @Test
  void orderFinalizeFailureResumesWithoutCancellingConfirmedStock() {
    doThrow(new RuntimeException("local finalize failure"))
        .doCallRealMethod()
        .when(transactions)
        .complete(anyLong(), anyString());
    var o = service.create(dto(), 7L, "request-key-00007");
    assertEquals(OrderStatus.CONFIRMING, o.getOrderStatus());
    retry(o.getId());
    assertEquals(1, events.count());
    assertEquals(OrderStatus.ORDERED, orders.findById(o.getId()).orElseThrow().getOrderStatus());
    verify(product, never()).release(anyString(), anyString());
  }

  @Test
  void outboxInsertFailureRollsBackOrderCompletion() {
    jdbc.execute("alter table order_outbox add constraint reject_new_events check(quantity < 0)");
    Long id;
    try {
      var order = service.create(dto(), 7L, "request-key-atomic-01");
      id = order.getId();
      assertEquals(OrderStatus.CONFIRMING, order.getOrderStatus());
      assertEquals(0, events.count());
    } finally {
      jdbc.execute("alter table order_outbox drop constraint reject_new_events");
    }
    retry(id);
    assertEquals(OrderStatus.ORDERED, orders.findById(id).orElseThrow().getOrderStatus());
    assertEquals(1, events.count());
  }

  @Test
  void concurrentSameKeyCreatesOneOrder() throws Exception {
    var pool = java.util.concurrent.Executors.newFixedThreadPool(2);
    var gate = new java.util.concurrent.CountDownLatch(1);
    try {
      var a =
          pool.submit(
              () -> {
                gate.await();
                return service.create(dto(), 7L, "request-key-race-01").getId();
              });
      var b =
          pool.submit(
              () -> {
                gate.await();
                return service.create(dto(), 7L, "request-key-race-01").getId();
              });
      gate.countDown();
      assertEquals(
          a.get(15, java.util.concurrent.TimeUnit.SECONDS),
          b.get(15, java.util.concurrent.TimeUnit.SECONDS));
      assertEquals(1, orders.count());
      assertEquals(1, events.count());
      verify(product, times(1)).reserve(anyString(), anyString(), any());
    } finally {
      pool.shutdownNow();
    }
  }

  @Test
  void otherMembersCannotReadOrder() {
    var o = service.create(dto(), 7L, "request-key-00008");
    assertThrows(
        org.springframework.web.server.ResponseStatusException.class,
        () -> service.owned(o.getId(), 8L));
    assertTrue(service.mine(8L).isEmpty());
  }

  @Test
  void snsFailureIsRetriedWithSameEventIdAndNoOrderRollback() throws Exception {
    var o = service.create(dto(), 7L, "request-key-00009");
    String eventId =
        jdbc.queryForObject(
            "select id from order_outbox where order_id=?", String.class, o.getId());
    var sns = mock(SnsClient.class);
    when(sns.publish(any(PublishRequest.class)))
        .thenThrow(new RuntimeException("SNS down"))
        .thenReturn(null);
    var dispatcher =
        new OrderNotification(
            events, outbox, sns, new ObjectMapper(), "topic", new SimpleMeterRegistry());
    dispatcher.send(eventId);
    assertEquals(
        "PENDING",
        jdbc.queryForObject("select status from order_outbox where id=?", String.class, eventId));
    jdbc.update("update order_outbox set next_attempt=null where id=?", eventId);
    dispatcher.send(eventId);
    dispatcher.send(eventId);
    assertEquals(
        "SENT",
        jdbc.queryForObject("select status from order_outbox where id=?", String.class, eventId));
    assertEquals(OrderStatus.ORDERED, orders.findById(o.getId()).orElseThrow().getOrderStatus());
    verify(sns, times(2)).publish(any(PublishRequest.class));
  }
}
