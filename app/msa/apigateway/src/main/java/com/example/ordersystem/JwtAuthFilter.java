package com.example.ordersystem;

import io.jsonwebtoken.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.gateway.filter.*;
import org.springframework.core.Ordered;
import org.springframework.http.*;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

@Component
public class JwtAuthFilter implements GlobalFilter, Ordered {
  private final String secretKey;

  public JwtAuthFilter(@Value("${jwt.secretKey}") String secretKey) {
    this.secretKey = secretKey;
  }

  // StripPrefix보다 먼저 실행하고, 클라이언트가 보낸 사용자 헤더를 제거한다.
  @Override
  public int getOrder() {
    return -100;
  }

  @Override
  public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
    String path = exchange.getRequest().getURI().getPath();
    HttpMethod method = exchange.getRequest().getMethod();
    ServerWebExchange clean =
        exchange
            .mutate()
            .request(
                b ->
                    b.headers(
                        h -> {
                          h.remove("X-User-Id");
                          h.remove("X-User-Role");
                          h.remove("X-Internal-Token");
                        }))
            .build();
    if (path.contains("/internal/")) return reject(exchange, HttpStatus.FORBIDDEN);
    if (isPublic(path, method)) return chain.filter(clean);
    // 외부에서 재고를 직접 변경하지 못하게 막는다.
    if (path.startsWith("/product-service/")
        && !HttpMethod.GET.equals(method)
        && !path.equals("/product-service/product/create")) {
      return reject(exchange, HttpStatus.FORBIDDEN);
    }
    try {
      String bearer = exchange.getRequest().getHeaders().getFirst(HttpHeaders.AUTHORIZATION);
      String token = bearer != null && bearer.startsWith("Bearer ") ? bearer.substring(7) : null;
      // 쿠키는 관리자 HTML을 확인하는 읽기 요청에서만 사용한다.
      if (token == null
          && HttpMethod.GET.equals(method)
          && path.equals("/member-service/member/admin-check")) {
        HttpCookie cookie = exchange.getRequest().getCookies().getFirst("ADMIN_ACCESS_TOKEN");
        token = cookie == null ? null : cookie.getValue();
      }
      if (token == null) return reject(exchange, HttpStatus.UNAUTHORIZED);
      Claims claims =
          Jwts.parserBuilder().setSigningKey(secretKey).build().parseClaimsJws(token).getBody();
      String id = claims.getSubject();
      String role = claims.get("role", String.class);
      if (id == null
          || !id.matches("[1-9][0-9]*")
          || !("USER".equals(role) || "ADMIN".equals(role))) {
        return reject(exchange, HttpStatus.UNAUTHORIZED);
      }
      boolean adminOnly =
          path.equals("/member-service/member/admin-check")
              || path.startsWith("/member-service/member/admin/")
              || path.equals("/product-service/product/create");
      if (adminOnly && !"ADMIN".equals(role)) return reject(exchange, HttpStatus.FORBIDDEN);
      return chain.filter(
          clean
              .mutate()
              .request(
                  b ->
                      b.headers(
                          h -> {
                            h.set("X-User-Id", id);
                            h.set("X-User-Role", "ROLE_" + role);
                          }))
              .build());
    } catch (JwtException | IllegalArgumentException e) {
      return reject(exchange, HttpStatus.UNAUTHORIZED);
    }
  }

  private boolean isPublic(String path, HttpMethod method) {
    if (HttpMethod.POST.equals(method)) {
      return path.equals("/member-service/member/create")
          || path.equals("/member-service/member/doLogin")
          || path.equals("/member-service/member/logout")
          || path.equals("/member-service/member/refresh-token");
    }
    return HttpMethod.GET.equals(method)
        && (path.equals("/product-service/product/list")
            || path.matches("/product-service/product/[0-9]+"));
  }

  private Mono<Void> reject(ServerWebExchange exchange, HttpStatus status) {
    exchange.getResponse().setStatusCode(status);
    return exchange.getResponse().setComplete();
  }
}
