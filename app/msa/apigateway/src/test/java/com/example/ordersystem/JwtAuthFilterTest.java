package com.example.ordersystem;

import static org.junit.jupiter.api.Assertions.*;

import io.jsonwebtoken.*;
import io.jsonwebtoken.security.Keys;
import java.util.Base64;
import java.util.Date;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.springframework.http.*;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

class JwtAuthFilterTest {
  private final byte[] key = new byte[64];
  private final JwtAuthFilter filter = new JwtAuthFilter(Base64.getEncoder().encodeToString(key));

  private String token(String role) {
    return Jwts.builder()
        .setSubject("7")
        .claim("role", role)
        .setExpiration(new Date(System.currentTimeMillis() + 60000))
        .signWith(Keys.hmacShaKeyFor(key))
        .compact();
  }

  @Test
  void internalApiCannotBeReachedEvenWithAdminToken() {
    for (String path :
        java.util.List.of(
            "/member-service/member/internal/7/email",
            "/product-service/product/internal/reservations/test")) {
      var exchange =
          MockServerWebExchange.from(
              MockServerHttpRequest.get(path)
                  .header("Authorization", "Bearer " + token("ADMIN"))
                  .header("X-Internal-Token", "forged"));
      filter.filter(exchange, ex -> fail("internal API must not be routed")).block();
      assertEquals(HttpStatus.FORBIDDEN, exchange.getResponse().getStatusCode());
    }
  }

  @Test
  void customerCannotOpenAdminEvenWithForgedHeader() {
    var exchange =
        MockServerWebExchange.from(
            MockServerHttpRequest.get("/member-service/member/admin-check")
                .header("Authorization", "Bearer " + token("USER"))
                .header("X-User-Role", "ROLE_ADMIN"));
    filter.filter(exchange, ex -> fail("must not route customer")).block();
    assertEquals(HttpStatus.FORBIDDEN, exchange.getResponse().getStatusCode());
    var create =
        MockServerWebExchange.from(
            MockServerHttpRequest.post("/product-service/product/create")
                .header("Authorization", "Bearer " + token("USER")));
    filter.filter(create, ex -> fail("customer must not register products")).block();
    assertEquals(HttpStatus.FORBIDDEN, create.getResponse().getStatusCode());
    var summary =
        MockServerWebExchange.from(
            MockServerHttpRequest.get("/member-service/member/admin/summary")
                .header("Authorization", "Bearer " + token("USER")));
    filter.filter(summary, ex -> fail("customer must not read operational data")).block();
    assertEquals(HttpStatus.FORBIDDEN, summary.getResponse().getStatusCode());
  }

  @Test
  void adminCookieIsAcceptedOnlyForReadCheck() {
    var exchange =
        MockServerWebExchange.from(
            MockServerHttpRequest.get("/member-service/member/admin-check")
                .cookie(new HttpCookie("ADMIN_ACCESS_TOKEN", token("ADMIN"))));
    AtomicReference<ServerWebExchange> routed = new AtomicReference<>();
    filter
        .filter(
            exchange,
            ex -> {
              routed.set(ex);
              return Mono.empty();
            })
        .block();
    assertEquals("ROLE_ADMIN", routed.get().getRequest().getHeaders().getFirst("X-User-Role"));
    var write =
        MockServerWebExchange.from(
            MockServerHttpRequest.post("/product-service/product/create")
                .cookie(new HttpCookie("ADMIN_ACCESS_TOKEN", token("ADMIN"))));
    filter.filter(write, ex -> fail("cookie must not authorize writes")).block();
    assertEquals(HttpStatus.UNAUTHORIZED, write.getResponse().getStatusCode());
  }

  @Test
  void identityHeadersAreReplacedAndPublicHeadersRemoved() {
    var exchange =
        MockServerWebExchange.from(
            MockServerHttpRequest.post("/ordering-service/ordering/create")
                .header("Authorization", "Bearer " + token("USER"))
                .header("X-User-Id", "1")
                .header("X-User-Role", "ROLE_ADMIN"));
    filter
        .filter(
            exchange,
            ex -> {
              assertEquals(java.util.List.of("7"), ex.getRequest().getHeaders().get("X-User-Id"));
              assertEquals(
                  java.util.List.of("ROLE_USER"), ex.getRequest().getHeaders().get("X-User-Role"));
              return Mono.empty();
            })
        .block();
    var publicRequest =
        MockServerWebExchange.from(
            MockServerHttpRequest.get("/product-service/product/list")
                .header("X-User-Id", "1")
                .header("X-User-Role", "ROLE_ADMIN"));
    filter
        .filter(
            publicRequest,
            ex -> {
              assertNull(ex.getRequest().getHeaders().getFirst("X-User-Id"));
              assertNull(ex.getRequest().getHeaders().getFirst("X-User-Role"));
              return Mono.empty();
            })
        .block();
  }

  @Test
  void unsignedAndExpiredTokensFailAndStockIsNotPublic() {
    for (String token :
        java.util.List.of(
            "invalid",
            Jwts.builder()
                .setSubject("7")
                .claim("role", "ADMIN")
                .setExpiration(new Date(1))
                .signWith(Keys.hmacShaKeyFor(key))
                .compact())) {
      var exchange =
          MockServerWebExchange.from(
              MockServerHttpRequest.get("/member-service/member/admin-check")
                  .header("Authorization", "Bearer " + token));
      filter.filter(exchange, ex -> fail("bad token")).block();
      assertEquals(HttpStatus.UNAUTHORIZED, exchange.getResponse().getStatusCode());
    }
    var stock =
        MockServerWebExchange.from(
            MockServerHttpRequest.put("/product-service/product/updatestock")
                .header("Authorization", "Bearer " + token("ADMIN")));
    filter.filter(stock, ex -> fail("external stock changes forbidden")).block();
    assertEquals(HttpStatus.FORBIDDEN, stock.getResponse().getStatusCode());
  }
}
