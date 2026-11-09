package com.example.ordersystem.member.controller;

import com.example.ordersystem.member.repository.MemberRepository;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/member/internal")
public class InternalMemberController {
  private final MemberRepository members;
  private final String token;

  public InternalMemberController(
      MemberRepository members, @Value("${INTERNAL_SERVICE_TOKEN:}") String token) {
    this.members = members;
    this.token = token;
  }

  @GetMapping("/{id}/email")
  public Map<String, String> email(
      @PathVariable Long id,
      @RequestHeader(value = "X-Internal-Token", required = false) String supplied) {
    if (token.length() < 32
        || supplied == null
        || !MessageDigest.isEqual(
            token.getBytes(StandardCharsets.UTF_8), supplied.getBytes(StandardCharsets.UTF_8)))
      throw new ResponseStatusException(HttpStatus.FORBIDDEN);
    return Map.of(
        "email",
        members
            .findById(id)
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND))
            .getEmail());
  }
}
