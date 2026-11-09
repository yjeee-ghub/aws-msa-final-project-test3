package com.example.ordersystem.ordering.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.*;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.*;
import org.springframework.data.domain.PageRequest;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.core.client.config.ClientOverrideConfiguration;
import software.amazon.awssdk.http.urlconnection.UrlConnectionHttpClient;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.sns.SnsClient;
import software.amazon.awssdk.services.sns.model.PublishRequest;

@Component
@ConditionalOnProperty(name = "ORDER_NOTIFICATIONS_ENABLED", havingValue = "true")
public class OrderNotification {
  private static final org.slf4j.Logger log =
      org.slf4j.LoggerFactory.getLogger(OrderNotification.class);
  private final OutboxRepository events;
  private final OutboxTransactions tx;
  private final SnsClient sns;
  private final ObjectMapper json;
  private final String topic;
  private final MeterRegistry metrics;

  public OrderNotification(
      OutboxRepository events,
      OutboxTransactions tx,
      SnsClient sns,
      ObjectMapper json,
      @Value("${ORDER_NOTIFICATION_TOPIC_ARN}") String topic,
      MeterRegistry metrics) {
    this.events = events;
    this.tx = tx;
    this.sns = sns;
    this.json = json;
    this.topic = topic;
    this.metrics = metrics;
  }

  @Scheduled(fixedDelayString = "${outbox.poll-ms:5000}")
  public void dispatch() {
    for (String id : events.due(Instant.now(), PageRequest.of(0, 20)))
      try {
        send(id);
      } catch (Exception unavailable) {
        /* DB 접근 실패는 임대 만료 후 다시 처리 */
      }
  }

  public void send(String id) throws Exception {
    String token = UUID.randomUUID().toString();
    var e = tx.claim(id, token);
    if (e == null) return;
    boolean sent = false;
    try {
      String body =
          json.writeValueAsString(
              Map.of(
                  "schemaVersion",
                  1,
                  "eventType",
                  "ORDER_CREATED",
                  "eventId",
                  e.id,
                  "orderId",
                  e.orderId,
                  "memberId",
                  e.memberId,
                  "recipientEmail",
                  e.recipientEmail,
                  "productName",
                  e.productName,
                  "quantity",
                  e.quantity,
                  "total",
                  e.total,
                  "occurredAt",
                  e.createdAt.toString()));
      sns.publish(PublishRequest.builder().topicArn(topic).message(body).build());
      sent = true;
    } catch (Exception failure) {
      log.warn("Outbox {} delivery failed ({})", id, failure.getClass().getSimpleName());
      metrics.counter("order_outbox_delivery", "result", "failed").increment();
    }
    // SNS 수락 후 DB 기록 전 종료되면 재발행될 수 있으므로 소비자에서도 eventId로 중복 처리한다.
    tx.finish(id, token, sent);
    if (sent) metrics.counter("order_outbox_delivery", "result", "sent").increment();
  }

  @Configuration
  @ConditionalOnProperty(name = "ORDER_NOTIFICATIONS_ENABLED", havingValue = "true")
  static class AwsConfig {
    @Bean(destroyMethod = "close")
    SnsClient orderSnsClient(@Value("${AWS_REGION:ap-northeast-2}") String region) {
      return SnsClient.builder()
          .region(Region.of(region))
          .httpClientBuilder(
              UrlConnectionHttpClient.builder()
                  .connectionTimeout(Duration.ofSeconds(2))
                  .socketTimeout(Duration.ofSeconds(3)))
          .overrideConfiguration(
              ClientOverrideConfiguration.builder().apiCallTimeout(Duration.ofSeconds(10)).build())
          .build();
    }
  }
}
