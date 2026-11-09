package com.example.ordersystem.member;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.Test;
import org.springframework.boot.actuate.autoconfigure.availability.AvailabilityHealthContributorAutoConfiguration;
import org.springframework.boot.actuate.autoconfigure.health.HealthEndpointAutoConfiguration;
import org.springframework.boot.actuate.autoconfigure.availability.AvailabilityProbesAutoConfiguration;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthEndpoint;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.boot.actuate.health.Status;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.autoconfigure.availability.ApplicationAvailabilityAutoConfiguration;
import org.springframework.boot.availability.AvailabilityChangeEvent;
import org.springframework.boot.availability.LivenessState;
import org.springframework.boot.availability.ReadinessState;
import org.springframework.boot.env.YamlPropertySourceLoader;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.core.io.ClassPathResource;
import static org.junit.jupiter.api.Assertions.*;

class HealthGroupsTest {
    @Test void databaseOutageStopsTrafficWithoutRequestingRestart() {
        var databaseUp = new AtomicBoolean(true);
        new ApplicationContextRunner()
                .withConfiguration(AutoConfigurations.of(ApplicationAvailabilityAutoConfiguration.class,
                        AvailabilityHealthContributorAutoConfiguration.class, AvailabilityProbesAutoConfiguration.class, HealthEndpointAutoConfiguration.class))
                // 운영과 같은 application.yml의 health group 설정을 그대로 읽습니다.
                .withInitializer(context -> {
                    try {
                        new YamlPropertySourceLoader().load("application", new ClassPathResource("application.yml"))
                                .forEach(source -> context.getEnvironment().getPropertySources().addLast(source));
                    } catch (IOException e) { throw new IllegalStateException(e); }
                })
                // 실제 AWS/DB 대신 DB health 결과만 전환해 probe의 역할을 검증합니다.
                .withBean("dbHealthIndicator", HealthIndicator.class,
                        () -> () -> databaseUp.get() ? Health.up().build() : Health.down().build())
                .run(context -> {
                    assertNull(context.getStartupFailure());
                    AvailabilityChangeEvent.publish(context, ReadinessState.ACCEPTING_TRAFFIC);
                    AvailabilityChangeEvent.publish(context, LivenessState.CORRECT);
                    var endpoint = context.getBean(HealthEndpoint.class);
                    assertEquals(Status.UP, endpoint.healthForPath("readiness").getStatus());
                    databaseUp.set(false);
                    assertEquals(Status.DOWN, endpoint.healthForPath("readiness").getStatus());
                    assertEquals(Status.UP, endpoint.healthForPath("liveness").getStatus());
                    databaseUp.set(true);
                    assertEquals(Status.UP, endpoint.healthForPath("readiness").getStatus());
                    AvailabilityChangeEvent.publish(context, LivenessState.BROKEN);
                    assertEquals(Status.DOWN, endpoint.healthForPath("liveness").getStatus());
                });
    }
}
