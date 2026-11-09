package com.example.ordersystem.member;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.example.ordersystem.member.controller.InternalMemberController;
import com.example.ordersystem.member.domain.Member;
import com.example.ordersystem.member.repository.MemberRepository;
import org.junit.jupiter.api.Test;

class InternalMemberAccessTest {
  @Test
  void emailRequiresInternalCredentialAndComesFromMemberDatabase() {
    var repository = mock(MemberRepository.class);
    String token = "local-test-internal-token-32-characters";
    var controller = new InternalMemberController(repository, token);
    assertThrows(
        org.springframework.web.server.ResponseStatusException.class,
        () -> controller.email(7L, null));
    assertThrows(
        org.springframework.web.server.ResponseStatusException.class,
        () -> controller.email(7L, "forged"));
    verifyNoInteractions(repository);
    when(repository.findById(7L))
        .thenReturn(
            java.util.Optional.of(Member.builder().id(7L).email("customer@example.com").build()));
    assertEquals("customer@example.com", controller.email(7L, token).get("email"));
  }
}
